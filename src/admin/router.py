"""Admin API router for tenant/folder management and ingestion orchestration."""
from __future__ import annotations

import importlib
import time
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal, TypeAlias

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..common.auth import AuthContext, require_api_key
from ..common.sse import stream_job_events
from .service import (
    AdminService,
    canonical_collection_name,
    collection_name_for_tenant,
    default_service,
)

router = APIRouter(prefix="/admin", tags=["admin"])

_SERVICE = default_service()


def get_service() -> AdminService:
    return _SERVICE


ServiceDep: TypeAlias = Annotated[AdminService, Depends(get_service)]
AuthKeysIssue: TypeAlias = Annotated[AuthContext, Depends(require_api_key(["keys:issue"]))]
AuthFoldersRead: TypeAlias = Annotated[AuthContext, Depends(require_api_key(["folders:read"]))]
AuthFoldersWrite: TypeAlias = Annotated[AuthContext, Depends(require_api_key(["folders:write"]))]
AuthIngestWrite: TypeAlias = Annotated[
    AuthContext,
    Depends(require_api_key(["folders:write", "ingest:write"])),
]
AuthJobsRead: TypeAlias = Annotated[AuthContext, Depends(require_api_key(["jobs:read"]))]


def _ingestor_metrics():
    metrics = importlib.import_module("src.ingestor.metrics")
    return metrics


def _record_metrics(action: str, request: Request, tenant: str, status_code: int, start: float) -> None:
    metrics = _ingestor_metrics()
    if not metrics.METRICS_ENABLED:
        return
    requests, _, latency = metrics.get_admin_metrics()
    requests.labels(route=action, method=request.method, code=str(status_code), tenant=tenant).inc()
    latency.labels(route=action).observe(time.perf_counter() - start)


def _record_failure(action: str, tenant: str, reason: str) -> None:
    metrics = _ingestor_metrics()
    if not metrics.METRICS_ENABLED:
        return
    _, failures, _ = metrics.get_admin_metrics()
    failures.labels(route=action, tenant=tenant, reason=reason).inc()


def _serialize_folder(folder) -> dict[str, Any]:
    return {
        "id": folder.id,
        "tenantId": folder.tenant_id,
        "path": folder.path,
        "slug": folder.slug,
        "parentId": folder.parent_id,
    }


def _serialize_job(job) -> dict[str, Any]:
    return {
        "id": job.id,
        "tenantId": job.tenant_id,
        "folderId": job.folder_id,
        "collection": job.collection_name,
        "status": job.status,
        "source_type": job.source_type,
        "source_value": job.source_value,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


class TenantCreate(BaseModel):
    slug: str = Field(..., min_length=1)


class FolderCreate(BaseModel):
    tenant: str | None = None
    path: str
    slug: str | None = None


class TaxonomyCreate(BaseModel):
    tenant: str | None = None
    facet: str
    value: str


class APIKeyRequest(BaseModel):
    tenant: str | None = None
    scopes: list[str]
    origins: list[str] | None = None
    note: str | None = None
    expires_at: str | None = None


class OneClickIngest(BaseModel):
    tenant: str | None = None
    folder_path: str = Field(..., min_length=1)
    source_type: Literal[
        "url",
        "gdrive",
        "gdrive_folder",
        "file",
        "html",
        "markdown",
        "pdf",
        "docx",
        "md",
        "video",
    ]
    source_value: str = Field(..., min_length=1)
    taxonomy: dict[str, str] = Field(default_factory=dict)
    mode: Literal["text", "multimodal"] = "text"
    idempotency_key: str | None = None


@router.post("/tenants")
def create_tenant(
    payload: TenantCreate,
    request: Request,
    auth: AuthKeysIssue,
    service: ServiceDep,
):
    start = time.perf_counter()
    try:
        tenant = service.create_tenant(payload.slug)
    except ValueError as exc:
        _record_failure("tenants.create", auth.tenant, str(exc))
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    _record_metrics("tenants.create", request, auth.tenant, 200, start)
    return {"tenant": tenant.slug}


@router.get("/folders")
def list_folders(
    request: Request,
    auth: AuthFoldersRead,
    service: ServiceDep,
    tenant: str | None = None,
    parent_id: int | None = None,
):
    start = time.perf_counter()
    tenant_slug = (tenant or auth.tenant).strip().lower()
    folders = service.list_folders(tenant_slug, parent_id)
    _record_metrics("folders.list", request, tenant_slug, 200, start)
    return {"tenant": tenant_slug, "folders": [_serialize_folder(folder) for folder in folders]}


@router.post("/folders")
def create_folder(
    payload: FolderCreate,
    request: Request,
    auth: AuthFoldersWrite,
    service: ServiceDep,
):
    start = time.perf_counter()
    tenant_slug = (payload.tenant or auth.tenant).strip().lower()
    try:
        folder = service.ensure_folder(tenant_slug, payload.path, slug=payload.slug)
    except ValueError as exc:
        _record_failure("folders.create", tenant_slug, str(exc))
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    collection_base = canonical_collection_name(folder.path)
    collection_full = collection_name_for_tenant(tenant_slug, collection_base)
    service.ensure_collection(tenant_slug, collection_full, folder=folder)
    _record_metrics("folders.create", request, tenant_slug, 200, start)
    return {
        "tenant": tenant_slug,
        "folder": _serialize_folder(folder),
        "collection": collection_full,
    }


@router.get("/taxonomy")
def get_taxonomy(
    request: Request,
    auth: AuthFoldersRead,
    service: ServiceDep,
    tenant: str | None = None,
):
    start = time.perf_counter()
    tenant_slug = (tenant or auth.tenant).strip().lower()
    facets = service.list_taxonomy(tenant_slug)
    _record_metrics("taxonomy.list", request, tenant_slug, 200, start)
    return {"tenant": tenant_slug, "facets": facets}


@router.post("/taxonomy")
def add_taxonomy(
    payload: TaxonomyCreate,
    request: Request,
    auth: AuthFoldersWrite,
    service: ServiceDep,
):
    start = time.perf_counter()
    tenant_slug = (payload.tenant or auth.tenant).strip().lower()
    try:
        record = service.add_taxonomy_value(tenant_slug, payload.facet, payload.value)
    except ValueError as exc:
        _record_failure("taxonomy.create", tenant_slug, str(exc))
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    _record_metrics("taxonomy.create", request, tenant_slug, 200, start)
    return {"tenant": tenant_slug, "facet": record.facet, "value": record.value}


@router.post("/api-keys")
def issue_api_key(
    payload: APIKeyRequest,
    request: Request,
    auth: AuthKeysIssue,
    service: ServiceDep,
):
    start = time.perf_counter()
    tenant_slug = (payload.tenant or auth.tenant).strip().lower()
    try:
        expires_at = datetime.fromisoformat(payload.expires_at) if payload.expires_at else None
    except ValueError as exc:
        _record_failure("api_keys.issue", tenant_slug, "bad_expiry_format")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid expires_at format") from exc
    try:
        record = service.issue_api_key(
            tenant_slug=tenant_slug,
            scopes=payload.scopes,
            origins=payload.origins,
            note=payload.note,
            expires_at=expires_at,
            prefix="rag",
        )
    except ValueError as exc:
        _record_failure("api_keys.issue", tenant_slug, str(exc))
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    _record_metrics("api_keys.issue", request, tenant_slug, 200, start)
    origins = record.origins.split(",") if record.origins else ["*"]
    scopes = record.scopes.split(",") if record.scopes else []
    return {
        "tenant": tenant_slug,
        "key": record.key,
        "scopes": scopes,
        "origins": origins,
        "note": record.note,
        "expires_at": record.expires_at.isoformat() if record.expires_at else None,
    }


@router.post("/ingest/oneclick", status_code=status.HTTP_202_ACCEPTED)
def ingest_oneclick(
    payload: OneClickIngest,
    request: Request,
    auth: AuthIngestWrite,
    service: ServiceDep,
):
    start = time.perf_counter()
    tenant_slug = (payload.tenant or auth.tenant).strip().lower()

    try:
        folder = service.ensure_folder(tenant_slug, payload.folder_path)
        collection_base = canonical_collection_name(folder.path)
        collection_full = collection_name_for_tenant(tenant_slug, collection_base)
        service.ensure_collection(tenant_slug, collection_full, folder=folder)
    except ValueError as exc:
        _record_failure("ingest.oneclick", tenant_slug, str(exc))
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    job_id = payload.idempotency_key or uuid.uuid4().hex
    existing_job = service.get_job(job_id)
    if existing_job is not None:
        _record_metrics("ingest.oneclick", request, tenant_slug, 202, start)
        return {
            "tenant": tenant_slug,
            "jobId": existing_job.id,
            "collection": existing_job.collection_name,
            "status": existing_job.status,
            "folder": folder.path,
        }

    job = service.create_job(
        job_id=job_id,
        tenant_slug=tenant_slug,
        folder_id=folder.id,
        collection_name=collection_full,
        source_type=payload.source_type,
        source_value=payload.source_value,
        status="queued",
    )
    service.append_job_event(job.id, "info", "Job queued for ingestion")
    service.update_job_status(job.id, "running")
    service.append_job_event(job.id, "info", f"Processing source {payload.source_type}")
    service.update_job_status(job.id, "done")
    taxonomy_snapshot = {key: value for key, value in payload.taxonomy.items() if value}
    service.append_job_event(
        job.id,
        "info",
        f"Ingestion completed for folder '{folder.path}'",
    )

    metadata = {
        "tenant": tenant_slug,
        "folder_path": folder.path,
        "collection": collection_full,
        "mode": payload.mode,
        "origin": auth.key,
        **taxonomy_snapshot,
    }

    _record_metrics("ingest.oneclick", request, tenant_slug, 202, start)
    return {
        "tenant": tenant_slug,
        "jobId": job.id,
        "collection": collection_full,
        "status": "done",
        "metadata": metadata,
    }


@router.get("/jobs")
def list_jobs(
    request: Request,
    auth: AuthJobsRead,
    service: ServiceDep,
    tenant: str | None = None,
    status_filter: str | None = None,
    limit: int = 50,
):
    start = time.perf_counter()
    tenant_slug = (tenant or auth.tenant).strip().lower()
    jobs = service.list_jobs(tenant_slug, status_filter=status_filter, limit=limit)
    _record_metrics("jobs.list", request, tenant_slug, 200, start)
    return {"tenant": tenant_slug, "jobs": [_serialize_job(job) for job in jobs]}


@router.get("/jobs/{job_id}")
def job_detail(
    job_id: str,
    request: Request,
    auth: AuthJobsRead,
    service: ServiceDep,
):
    start = time.perf_counter()
    job = service.get_job(job_id)
    if job is None:
        _record_failure("jobs.detail", auth.tenant, "not_found")
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Job not found")
    _record_metrics("jobs.detail", request, auth.tenant, 200, start)
    return _serialize_job(job)


@router.get("/jobs/{job_id}/events")
async def job_events(
    job_id: str,
    request: Request,
    auth: AuthJobsRead,
    service: ServiceDep,
):
    start = time.perf_counter()
    job = service.get_job_for_tenant(job_id, auth.tenant)
    if job is None:
        _record_failure("jobs.events", auth.tenant, "not_found")
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Job not found for tenant")
    _record_metrics("jobs.events", request, auth.tenant, 200, start)
    return StreamingResponse(
        stream_job_events(service, job_id, auth.tenant),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )