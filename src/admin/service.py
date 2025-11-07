"""Service helpers wrapping admin models."""
from __future__ import annotations

import datetime as dt
import hashlib
import logging
import re
import secrets
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from . import models
from .models import (
    DEFAULT_FACETS,
    ApiKey,
    Collection,
    Folder,
    Job,
    JobEvent,
    TaxonomyValue,
    Tenant,
)

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _normalize_path(path: str) -> str:
    cleaned = path.strip().strip("/")
    if not cleaned:
        raise ValueError("Folder path cannot be empty")
    parts = [segment for segment in cleaned.split("/") if segment]
    return "/".join(parts)


def _last_segment(path: str) -> str:
    return path.split("/")[-1]

__all__ = [
    "AdminService",
    "canonical_collection_name",
    "collection_name_for_tenant",
    "default_service",
    "normalize_collection_slug",
    "strip_collection_tenant_prefix",
]


def normalize_collection_slug(path_or_slug: str) -> str:
    text = path_or_slug.strip().lower()
    text = _SLUG_RE.sub("-", text)
    text = text.strip("-")
    if len(text) >= 3:
        return text
    digest = hashlib.sha1(path_or_slug.encode("utf-8")).hexdigest()[:12]
    return f"col-{digest}"


def canonical_collection_name(base: str) -> str:
    return normalize_collection_slug(base)


def collection_name_for_tenant(tenant_slug: str, base: str) -> str:
    return f"{tenant_slug}__{normalize_collection_slug(base)}"


def strip_collection_tenant_prefix(name: str, tenant_slug: str) -> str:
    prefix = f"{tenant_slug}__"
    if name.startswith(prefix):
        return name[len(prefix) :]
    return name


class AdminService:
    """High-level accessors around the admin SQLite database."""

    def __init__(self, engine: sa.engine.Engine | None = None) -> None:
        self._engine = engine or models.init_engine()
        self._session_factory: sessionmaker[Session] = models.init_session_factory(self._engine)
        self._bootstrap_lock = threading.RLock()
        self._bootstrapped = False

    def bootstrap(self) -> None:
        with self._bootstrap_lock:
            if self._bootstrapped:
                return
            models.bootstrap_database(self._engine)
            self._bootstrapped = True

    @contextmanager
    def session_scope(self) -> Iterator[Session]:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:  # pragma: no cover - defensive logging
            session.rollback()
            logger.exception("AdminService session rollback")
            raise
        finally:
            session.close()

    # --- Tenants ---

    def list_tenants(self) -> list[str]:
        self.bootstrap()
        with self.session_scope() as session:
            rows = session.scalars(sa.select(Tenant.slug).order_by(Tenant.slug)).all()
            return list(rows)

    def get_tenant(self, slug: str) -> Tenant | None:
        self.bootstrap()
        with self.session_scope() as session:
            return session.scalar(sa.select(Tenant).where(Tenant.slug == slug))

    def create_tenant(self, slug: str) -> Tenant:
        normalized = slug.strip().lower()
        if not normalized:
            raise ValueError("Tenant slug cannot be empty")
        self.bootstrap()
        with self.session_scope() as session:
            existing = session.scalar(sa.select(Tenant).where(Tenant.slug == normalized))
            if existing:
                return existing
            tenant = Tenant(slug=normalized)
            session.add(tenant)
            session.flush()
            return tenant

    # --- Taxonomy ---

    def list_taxonomy(self, tenant_slug: str) -> dict[str, list[str]]:
        self.bootstrap()
        with self.session_scope() as session:
            tenant = session.scalar(sa.select(Tenant).where(Tenant.slug == tenant_slug))
            if tenant is None:
                return {}
            rows = session.scalars(
                sa.select(TaxonomyValue).where(TaxonomyValue.tenant_id == tenant.id)
            ).all()
        facets: dict[str, list[str]] = {facet: [] for facet in DEFAULT_FACETS.get(tenant_slug, [])}
        for item in rows:
            facets.setdefault(item.facet, []).append(item.value)
        for values in facets.values():
            values.sort()
        return facets

    def add_taxonomy_value(self, tenant_slug: str, facet: str, value: str) -> TaxonomyValue:
        cleaned_facet = facet.strip().lower()
        cleaned_value = value.strip()
        if not cleaned_value:
            raise ValueError("Taxonomy value cannot be empty")
        allowed = DEFAULT_FACETS.get(tenant_slug)
        if allowed and cleaned_facet not in allowed:
            raise ValueError(f"Facet '{cleaned_facet}' not allowed for tenant '{tenant_slug}'")
        self.bootstrap()
        with self.session_scope() as session:
            tenant = self._tenant_row(session, tenant_slug)
            existing = session.scalar(
                sa.select(TaxonomyValue).where(
                    TaxonomyValue.tenant_id == tenant.id,
                    TaxonomyValue.facet == cleaned_facet,
                    TaxonomyValue.value == cleaned_value,
                )
            )
            if existing:
                return existing
            record = TaxonomyValue(
                tenant_id=tenant.id,
                facet=cleaned_facet,
                value=cleaned_value,
            )
            session.add(record)
            session.flush()
            return record

    # --- Folders & Collections (minimal scaffolding) ---

    def _tenant_row(self, session: Session, tenant_slug: str) -> Tenant:
        tenant = session.scalar(sa.select(Tenant).where(Tenant.slug == tenant_slug))
        if tenant is None:
            raise ValueError(f"Unknown tenant '{tenant_slug}'")
        return tenant

    def list_folders(self, tenant_slug: str, parent_id: int | None = None) -> list[Folder]:
        self.bootstrap()
        with self.session_scope() as session:
            tenant = self._tenant_row(session, tenant_slug)
            stmt = sa.select(Folder).where(Folder.tenant_id == tenant.id)
            if parent_id is None:
                stmt = stmt.where(Folder.parent_id.is_(None))
            else:
                stmt = stmt.where(Folder.parent_id == parent_id)
            stmt = stmt.order_by(Folder.path)
            return list(session.scalars(stmt).all())

    def ensure_folder(self, tenant_slug: str, path: str, slug: str | None = None) -> Folder:
        self.bootstrap()
        with self.session_scope() as session:
            tenant = self._tenant_row(session, tenant_slug)
            normalized_path = _normalize_path(path)
            parent: Folder | None = None
            segments: list[str] = []
            for segment in normalized_path.split("/"):
                segments.append(segment)
                current_path = "/".join(segments)
                existing = session.scalar(
                    sa.select(Folder).where(
                        Folder.tenant_id == tenant.id,
                        Folder.path == current_path,
                    )
                )
                if existing:
                    parent = existing
                    continue
                folder_slug = slug if current_path == normalized_path and slug else normalize_collection_slug(segment)
                record = Folder(
                    tenant_id=tenant.id,
                    path=current_path,
                    slug=folder_slug,
                    parent_id=parent.id if parent else None,
                )
                session.add(record)
                session.flush()
                parent = record
            assert parent is not None  # for mypy
            return parent

    def ensure_collection(self, tenant_slug: str, name: str, folder: Folder | None = None) -> Collection:
        self.bootstrap()
        with self.session_scope() as session:
            tenant = session.scalar(sa.select(Tenant).where(Tenant.slug == tenant_slug))
            if tenant is None:
                raise ValueError(f"Unknown tenant '{tenant_slug}'")
            found = session.scalar(
                sa.select(Collection).where(Collection.name == name)
            )
            if found:
                return found
            folder_id = folder.id if folder else None
            record = Collection(tenant_id=tenant.id, name=name, folder_id=folder_id)
            session.add(record)
            session.flush()
            return record

    def get_collection(self, name: str) -> Collection | None:
        self.bootstrap()
        with self.session_scope() as session:
            return session.scalar(sa.select(Collection).where(Collection.name == name))

    def list_collections(self, tenant_slug: str) -> list[Collection]:
        self.bootstrap()
        with self.session_scope() as session:
            tenant = self._tenant_row(session, tenant_slug)
            stmt = sa.select(Collection).where(Collection.tenant_id == tenant.id).order_by(Collection.created_at)
            return list(session.scalars(stmt).all())

    def get_folder_by_path(self, tenant_slug: str, path: str) -> Folder | None:
        normalized = _normalize_path(path)
        self.bootstrap()
        with self.session_scope() as session:
            tenant = self._tenant_row(session, tenant_slug)
            return session.scalar(
                sa.select(Folder).where(
                    Folder.tenant_id == tenant.id,
                    Folder.path == normalized,
                )
            )

    # --- API keys ---

    def issue_api_key(
        self,
        *,
        tenant_slug: str,
        scopes: Sequence[str],
        origins: Sequence[str] | None = None,
        note: str | None = None,
        expires_at: datetime | None = None,
        prefix: str = "rag",
    ) -> ApiKey:
        token = f"{prefix}_{secrets.token_urlsafe(24)}"
        self.bootstrap()
        with self.session_scope() as session:
            tenant = self._tenant_row(session, tenant_slug)
            data_scopes = ",".join(sorted({scope.strip() for scope in scopes if scope.strip()}))
            if not data_scopes:
                raise ValueError("At least one scope must be provided")
            origin_list = origins or ["*"]
            clean_origins = ",".join(sorted({origin.strip() for origin in origin_list if origin.strip()}))
            record = ApiKey(
                key=token,
                tenant_id=tenant.id,
                scopes=data_scopes,
                origins=clean_origins or "*",
                note=note,
                expires_at=expires_at,
            )
            session.add(record)
            session.flush()
            return record

    def list_api_keys(self, tenant_slug: str | None = None) -> list[ApiKey]:
        self.bootstrap()
        with self.session_scope() as session:
            stmt = sa.select(ApiKey)
            if tenant_slug:
                tenant = self._tenant_row(session, tenant_slug)
                stmt = stmt.where(ApiKey.tenant_id == tenant.id)
            return list(session.scalars(stmt).all())

    def delete_api_key(self, key: str) -> None:
        self.bootstrap()
        with self.session_scope() as session:
            record = session.get(ApiKey, key)
            if record is None:
                return
            session.delete(record)

    def get_api_key(self, key: str) -> ApiKey | None:
        self.bootstrap()
        with self.session_scope() as session:
            return session.get(ApiKey, key)

    # --- Jobs ---

    def create_job(
        self,
        *,
        job_id: str,
        tenant_slug: str,
        folder_id: int | None,
        collection_name: str,
        source_type: str,
        source_value: str,
        status: str = "queued",
    ) -> Job:
        self.bootstrap()
        with self.session_scope() as session:
            tenant_id = session.scalar(
                sa.select(Tenant.id).where(Tenant.slug == tenant_slug)
            )
            if tenant_id is None:
                raise ValueError(f"Unknown tenant '{tenant_slug}'")
            job = Job(
                id=job_id,
                tenant_id=tenant_id,
                folder_id=folder_id,
                collection_name=collection_name,
                source_type=source_type,
                source_value=source_value,
                status=status,
            )
            session.add(job)
            session.flush()
            return job

    def append_job_event(self, job_id: str, level: str, message: str) -> JobEvent:
        self.bootstrap()
        with self.session_scope() as session:
            job = session.get(Job, job_id)
            if job is None:
                raise ValueError(f"Unknown job '{job_id}'")
            event = JobEvent(job_id=job_id, level=level, message=message)
            job.updated_at = dt.datetime.now(dt.UTC)
            session.add(event)
            session.flush()
            return event

    def list_jobs(self, tenant_slug: str, status_filter: str | None = None, limit: int = 50) -> list[Job]:
        self.bootstrap()
        limit = max(1, min(limit, 200))
        with self.session_scope() as session:
            tenant = self._tenant_row(session, tenant_slug)
            stmt = sa.select(Job).where(Job.tenant_id == tenant.id)
            if status_filter:
                stmt = stmt.where(Job.status == status_filter)
            stmt = stmt.order_by(Job.created_at.desc()).limit(limit)
            return list(session.scalars(stmt).all())

    def get_job(self, job_id: str) -> Job | None:
        self.bootstrap()
        with self.session_scope() as session:
            return session.get(Job, job_id)

    def list_job_events(self, job_id: str, limit: int = 200) -> list[JobEvent]:
        self.bootstrap()
        limit = max(1, min(limit, 500))
        with self.session_scope() as session:
            stmt = (
                sa.select(JobEvent)
                .where(JobEvent.job_id == job_id)
                .order_by(JobEvent.timestamp.asc())
                .limit(limit)
            )
            return list(session.scalars(stmt).all())

    def list_job_events_since(
        self,
        job_id: str,
        after_id: int | None,
        limit: int = 200,
    ) -> list[JobEvent]:
        self.bootstrap()
        limit = max(1, min(limit, 500))
        with self.session_scope() as session:
            stmt = (
                sa.select(JobEvent)
                .where(JobEvent.job_id == job_id)
                .order_by(JobEvent.id.asc())
                .limit(limit)
            )
            if after_id is not None:
                stmt = stmt.where(JobEvent.id > after_id)
            return list(session.scalars(stmt).all())

    def get_job_for_tenant(self, job_id: str, tenant_slug: str) -> Job | None:
        self.bootstrap()
        with self.session_scope() as session:
            stmt = (
                sa.select(Job)
                .join(Tenant, Job.tenant_id == Tenant.id)
                .where(Job.id == job_id, Tenant.slug == tenant_slug)
            )
            return session.scalar(stmt)

    def update_job_status(self, job_id: str, status: str) -> Job | None:
        normalized = status.strip().lower()
        if not normalized:
            raise ValueError("Job status cannot be empty")
        self.bootstrap()
        with self.session_scope() as session:
            job = session.get(Job, job_id)
            if job is None:
                return None
            job.status = normalized
            job.updated_at = dt.datetime.now(dt.UTC)
            session.add(job)
            session.flush()
            return job


def default_service() -> AdminService:
    service = AdminService()
    service.bootstrap()
    return service
