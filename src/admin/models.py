"""Database models and bootstrap utilities for the admin data layer."""
from __future__ import annotations

import datetime as dt
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    foreign,
    mapped_column,
    relationship,
    sessionmaker,
)

DEFAULT_TENANTS = ("edu", "web3")
DEFAULT_FACETS = {
    "edu": ["doc_type", "domain", "level", "matiere", "track"],
    "web3": ["topic", "chain", "tool", "difficulty"],
}
DEFAULT_DIFFICULTY_VALUES = ["beginner", "intermediate", "advanced"]
ADMIN_DB_ENV = "ADMIN_DB_PATH"
ADMIN_DB_BASEDIR_ENV = "ADMIN_DB_BASEDIR"
DEFAULT_ADMIN_DB_PATH = Path("/srv/rag-admin/admin.db")


def _utcnow() -> dt.datetime:
    """Return an aware UTC timestamp compatible with SQLAlchemy defaults."""
    return dt.datetime.now(dt.UTC)


def _ensure_admin_directory(path: Path) -> None:
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)


def admin_db_path() -> Path:
    override = os.getenv(ADMIN_DB_ENV)
    if override:
        location = Path(override)
        if not location.is_absolute():
            base_dir = os.getenv(ADMIN_DB_BASEDIR_ENV)
            base_path = Path(base_dir) if base_dir else Path.cwd()
            location = (base_path / location).resolve()
    else:
        location = DEFAULT_ADMIN_DB_PATH
    _ensure_admin_directory(location)
    return location


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False)

    folders: Mapped[list[Folder]] = relationship("Folder", back_populates="tenant")
    taxonomy_values: Mapped[list[TaxonomyValue]] = relationship("TaxonomyValue", back_populates="tenant")
    collections: Mapped[list[Collection]] = relationship("Collection", back_populates="tenant")
    api_keys: Mapped[list[ApiKey]] = relationship("ApiKey", back_populates="tenant")
    jobs: Mapped[list[Job]] = relationship("Job", back_populates="tenant")


class Folder(Base):
    __tablename__ = "folders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    path: Mapped[str] = mapped_column(sa.String(512), nullable=False)
    slug: Mapped[str | None] = mapped_column(sa.String(128))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("folders.id", ondelete="SET NULL"))

    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="folders")
    parent: Mapped[Folder | None] = relationship("Folder", remote_side="Folder.id", back_populates="children")
    children: Mapped[list[Folder]] = relationship(
        "Folder",
        back_populates="parent",
        cascade="all, delete-orphan",
        single_parent=True,
    )
    collections: Mapped[list[Collection]] = relationship("Collection", back_populates="folder")
    jobs: Mapped[list[Job]] = relationship("Job", back_populates="folder")

    __table_args__ = (
        UniqueConstraint("tenant_id", "path", name="uq_folder_tenant_path"),
    )


class TaxonomyValue(Base):
    __tablename__ = "taxonomy_values"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    facet: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    value: Mapped[str] = mapped_column(sa.String(128), nullable=False)

    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="taxonomy_values")

    __table_args__ = (
        UniqueConstraint("tenant_id", "facet", "value", name="uq_taxonomy_tenant_facet_value"),
    )


class Collection(Base):
    __tablename__ = "collections"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    folder_id: Mapped[int | None] = mapped_column(ForeignKey("folders.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(sa.String(256), unique=True, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )

    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="collections")
    folder: Mapped[Folder | None] = relationship("Folder", back_populates="collections")
    jobs: Mapped[list[Job]] = relationship(
        "Job",
        back_populates="collection_ref",
        primaryjoin=lambda: Collection.name == foreign(Job.collection_name),
        foreign_keys=lambda: [Job.collection_name],
    )


class ApiKey(Base):
    __tablename__ = "api_keys"

    key: Mapped[str] = mapped_column(sa.String(128), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    scopes: Mapped[str] = mapped_column(sa.Text, nullable=False, default="")
    origins: Mapped[str] = mapped_column(sa.Text, nullable=False, default="*")
    note: Mapped[str | None] = mapped_column(sa.String(256))
    expires_at: Mapped[dt.datetime | None] = mapped_column(sa.DateTime(timezone=True))

    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="api_keys")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    folder_id: Mapped[int | None] = mapped_column(ForeignKey("folders.id", ondelete="SET NULL"))
    collection_name: Mapped[str | None] = mapped_column(
        sa.String(256),
        ForeignKey("collections.name", ondelete="SET NULL"),
        nullable=True,
    )
    source_type: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    source_value: Mapped[str] = mapped_column(sa.Text, nullable=False)
    status: Mapped[str] = mapped_column(sa.String(16), nullable=False, default="queued")
    created_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        sa.DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )

    tenant: Mapped[Tenant] = relationship("Tenant", back_populates="jobs")
    folder: Mapped[Folder | None] = relationship("Folder", back_populates="jobs")
    collection_ref: Mapped[Collection | None] = relationship(
        "Collection",
        back_populates="jobs",
        primaryjoin=lambda: foreign(Job.collection_name) == Collection.name,
        foreign_keys=lambda: [Job.collection_name],
    )
    events: Mapped[list[JobEvent]] = relationship("JobEvent", back_populates="job", cascade="all, delete-orphan")


class JobEvent(Base):
    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    timestamp: Mapped[dt.datetime] = mapped_column(sa.DateTime(timezone=True), default=_utcnow, nullable=False)
    level: Mapped[str] = mapped_column(sa.String(16), nullable=False, default="info")
    message: Mapped[str] = mapped_column(sa.Text, nullable=False)

    job: Mapped[Job] = relationship("Job", back_populates="events")


def init_engine(echo: bool = False) -> Engine:
    database_path = admin_db_path()
    url = f"sqlite:///{database_path}"
    return sa.create_engine(
        url,
        echo=echo,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )


def init_session_factory(engine: Engine | None = None) -> sessionmaker[Any]:
    engine = engine or init_engine()
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _seed_tenants(session: Session) -> None:
    existing = {tenant.slug for tenant in session.scalars(sa.select(Tenant)).all()}
    configured = {
        slug.strip()
        for slug in os.getenv("TENANTS", ",".join(DEFAULT_TENANTS)).split(",")
        if slug.strip()
    }
    target_slugs = configured or set(DEFAULT_TENANTS)
    for slug in target_slugs:
        if slug not in existing:
            session.add(Tenant(slug=slug))
    session.flush()


def _seed_taxonomy(session: Session) -> None:
    tenants = {tenant.slug: tenant.id for tenant in session.scalars(sa.select(Tenant)).all()}
    for slug, facets in DEFAULT_FACETS.items():
        tenant_id = tenants.get(slug)
        if tenant_id is None:
            continue
        for facet in facets:
            defaults: Iterable[str]
            if slug == "web3" and facet == "difficulty":
                defaults = DEFAULT_DIFFICULTY_VALUES
            else:
                defaults = ()
            for value in defaults:
                exists = session.scalar(
                    sa.select(TaxonomyValue).where(
                        TaxonomyValue.tenant_id == tenant_id,
                        TaxonomyValue.facet == facet,
                        TaxonomyValue.value == value,
                    )
                )
                if not exists:
                    session.add(
                        TaxonomyValue(
                            tenant_id=tenant_id,
                            facet=facet,
                            value=value,
                        )
                    )


def bootstrap_database(engine: Engine | None = None) -> None:
    engine = engine or init_engine()
    Base.metadata.create_all(engine)
    session_factory = init_session_factory(engine)
    with session_factory.begin() as session:
        _seed_tenants(session)
        _seed_taxonomy(session)

