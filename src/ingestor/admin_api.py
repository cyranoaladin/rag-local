from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any, Optional

import requests
from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

try:
    from . import audit_logger as audit_logger
    from . import catalog as catalog
except Exception:  # pragma: no cover - executed when running as top-level module
    import importlib as _importlib
    try:
        catalog = _importlib.import_module("src.ingestor.catalog")
        audit_logger = _importlib.import_module("src.ingestor.audit_logger")
    except Exception:
        try:
            catalog = _importlib.import_module("ingestor.catalog")
            audit_logger = _importlib.import_module("ingestor.audit_logger")
        except Exception:
            catalog = _importlib.import_module("catalog")
            audit_logger = _importlib.import_module("audit_logger")

router = APIRouter(prefix="/admin", tags=["admin"])
_logger = logging.getLogger(__name__)
_audit = audit_logger.get_audit_logger()


def _get_client_ip(request: Request) -> str:
    """Extract client IP from request headers."""
    headers: Mapping[str, str] = request.headers
    forwarded = headers.get("X-Forwarded-For") or headers.get("x-forwarded-for")
    if isinstance(forwarded, str) and forwarded.strip():
        return forwarded.split(",")[0].strip()
    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    return host or "unknown"


def _get_request_id(request: Request) -> Optional[str]:
    """Extract request ID from headers for tracing."""
    headers: Mapping[str, str] = request.headers
    return headers.get("X-Request-ID") or headers.get("x-request-id")


# --- Security: reuse same token as /ingest (Bearer or X-API-Token) ---

def _admin_guard(request: Request) -> None:
    token_env = os.getenv("INGESTOR_API_TOKEN") or os.getenv("INGEST_AUTH_TOKEN")
    client_ip = _get_client_ip(request)
    request_id = _get_request_id(request)
    
    if not token_env:
        return  # no guard configured
    header_token = request.headers.get("X-API-Token") or request.headers.get("x-api-token")
    if not header_token:
        auth = request.headers.get("Authorization") or request.headers.get("authorization")
        if isinstance(auth, str) and auth.strip():
            value = auth.strip()
            if value.lower().startswith("bearer "):
                header_token = value.split(" ", 1)[1].strip()
            else:
                header_token = value
    if header_token != token_env:
        # Log security violation
        _audit.log_security_violation(
            violation_type="invalid_admin_token",
            client_ip=client_ip,
            details={"header_provided": bool(header_token)},
            request_id=request_id,
        )
        raise HTTPException(status_code=401, detail="Unauthorized")


def _ensure_upload_dir() -> str:
    """Return a writable directory for admin uploads, creating it if needed."""
    path = os.getenv("ADMIN_UPLOAD_DIR", "/data/uploads")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as exc:  # pragma: no cover - unexpected filesystem issues
        _logger.error("Unable to create admin upload directory '%s'", path, exc_info=True)
        raise HTTPException(status_code=500, detail="Admin upload directory unavailable") from exc
    return path


@router.get("/health")
def admin_health(request: Request) -> dict[str, str]:
    """Basic readiness probe for admin integrations (no auth required)."""
    _ensure_upload_dir()
    catalog.init_db(os.getenv("ADMIN_DB_PATH"))
    return {"status": "ok"}


# --- Catalog models ---

class CreateDocumentPayload(BaseModel):
    domain: str = Field(description="lycee | web3 | ...")
    title: Optional[str] = None
    source_type: str = Field(description="url|gdrive_folder|pdf|docx|markdown|md|video")
    source_location: str
    tags: Optional[list[str]] = None
    metadata: Optional[dict[str, Any]] = None


@router.post("/documents")
def create_document(payload: CreateDocumentPayload, request: Request) -> dict[str, Any]:
    _admin_guard(request)
    client_ip = _get_client_ip(request)
    request_id = _get_request_id(request)
    
    doc = catalog.create_document(
        domain=payload.domain.strip(),
        source_type=payload.source_type.strip(),
        source_location=payload.source_location.strip(),
        title=(payload.title.strip() if payload.title else None),
        tags=[t.strip() for t in (payload.tags or []) if t and t.strip()],
        metadata=payload.metadata or {},
        path=os.getenv("ADMIN_DB_PATH"),
    )
    
    # Audit log
    _audit.log_success(
        action=audit_logger.AuditAction.DOCUMENT_CREATE,
        client_ip=client_ip,
        resource_type="document",
        resource_id=doc.get("id"),
        details={"domain": payload.domain, "source_type": payload.source_type},
        request_id=request_id,
    )
    
    return doc


@router.get("/documents")
def list_documents(request: Request, domain: Optional[str] = Query(default=None)) -> dict[str, Any]:
    _admin_guard(request)
    client_ip = _get_client_ip(request)
    request_id = _get_request_id(request)
    
    db_path = os.getenv("ADMIN_DB_PATH")
    docs = catalog.list_documents(domain=domain.strip() if domain else None, path=db_path)
    
    # Audit log
    _audit.log_success(
        action=audit_logger.AuditAction.DOCUMENT_LIST,
        client_ip=client_ip,
        resource_type="document",
        details={"domain_filter": domain, "count": len(docs)},
        request_id=request_id,
    )
    
    return {"documents": docs}


@router.get("/documents/{document_id}/ingestions")
def list_doc_ingestions(document_id: str, request: Request) -> dict[str, Any]:
    _admin_guard(request)
    runs = catalog.list_ingestions(document_id=document_id, path=os.getenv("ADMIN_DB_PATH"))
    return {"ingestions": runs}


@router.post("/documents/{document_id}/ingest")
def ingest_document(document_id: str, request: Request) -> dict[str, Any]:
    _admin_guard(request)
    client_ip = _get_client_ip(request)
    request_id = _get_request_id(request)
    
    db_path = os.getenv("ADMIN_DB_PATH")
    doc = catalog.get_document(document_id, path=db_path)
    if not doc:
        _audit.log_failure(
            action=audit_logger.AuditAction.DOCUMENT_INGEST,
            reason="document_not_found",
            client_ip=client_ip,
            resource_type="document",
            resource_id=document_id,
            request_id=request_id,
        )
        raise HTTPException(status_code=404, detail="Document not found")
    
    run = catalog.create_ingestion_run(document_id=document_id, path=db_path)

    # Build ingest payload
    tags_csv = ",".join(doc.get("tags", []) or [])
    hints: dict[str, str] = {"domain": doc.get("domain", ""), "document_id": document_id}
    # flatten metadata (stringify values)
    for k, v in (doc.get("metadata") or {}).items():
        if v is None:
            continue
        hints[str(k)] = str(v)
    if tags_csv:
        hints["tags"] = tags_csv

    ingest_payload = {
        "source_type": doc["source_type"],
        "source": doc["source_location"],
        "hints": hints,
    }

    base_url = f"http://127.0.0.1:{int(os.getenv('INGESTOR_PORT', '8001') or '8001')}"
    token = os.getenv("INGESTOR_API_TOKEN") or os.getenv("INGEST_AUTH_TOKEN")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        timeout_s = int(os.getenv("ADMIN_INGEST_TIMEOUT_SECONDS", "1800") or "1800")
        resp = requests.post(
            f"{base_url}/ingest",
            json=ingest_payload,
            timeout=timeout_s,
            headers=headers,
        )
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        body = resp.json() if content_type.startswith("application/json") else {}
        added = int(body.get("added", 0)) if isinstance(body, dict) else 0
        catalog.finish_ingestion_run(
            run["id"],
            status="success",
            error_message=None,
            chunks_count=added,
            path=db_path,
        )
        
        # Audit log
        _audit.log_success(
            action=audit_logger.AuditAction.DOCUMENT_INGEST,
            client_ip=client_ip,
            resource_type="document",
            resource_id=document_id,
            details={"chunks_added": added, "source_type": doc["source_type"]},
            request_id=request_id,
        )
        return {"status": "ok", "run": run, "result": body}
    except Exception as exc:
        catalog.finish_ingestion_run(
            run["id"],
            status="error",
            error_message=str(exc),
            chunks_count=None,
            path=db_path,
        )
        
        # Audit log - failure
        _audit.log_failure(
            action=audit_logger.AuditAction.DOCUMENT_INGEST,
            reason=str(exc),
            client_ip=client_ip,
            resource_type="document",
            resource_id=document_id,
            request_id=request_id,
        )
        raise HTTPException(status_code=500, detail=f"Admin ingest failed: {exc}") from exc


@router.post("/reindex")
def trigger_reindex(request: Request, payload: Optional[dict[str, Any]] = None) -> dict[str, str]:
    """Placeholder endpoint for batch reindex orchestration (no auth required).

    The actual implementation is environment-specific; for now we acknowledge the
    call so that automation hooks can validate connectivity.
    """
    _ = payload
    _ensure_upload_dir()
    _logger.info("Received reindex request via admin API")
    raise HTTPException(status_code=503, detail="Reindexing backend not configured")


@router.get("/documents/{document_id}")
def get_document_detail(document_id: str, request: Request) -> dict[str, Any]:
    _admin_guard(request)
    client_ip = _get_client_ip(request)
    request_id = _get_request_id(request)
    
    db_path = os.getenv("ADMIN_DB_PATH")
    doc = catalog.get_document(document_id, path=db_path)
    if not doc:
        # Audit log - not found
        _audit.log_failure(
            action=audit_logger.AuditAction.DOCUMENT_READ,
            reason="document_not_found",
            client_ip=client_ip,
            resource_type="document",
            resource_id=document_id,
            request_id=request_id,
        )
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Audit log
    _audit.log_success(
        action=audit_logger.AuditAction.DOCUMENT_READ,
        client_ip=client_ip,
        resource_type="document",
        resource_id=document_id,
        request_id=request_id,
    )
    return doc


@router.patch("/documents/{document_id}")
async def update_document_detail(document_id: str, request: Request) -> dict[str, Any]:
    _admin_guard(request)
    client_ip = _get_client_ip(request)
    request_id = _get_request_id(request)
    
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")
    forbidden = {"domain", "source_type", "source_location"}
    if any(k in body for k in forbidden):
        raise HTTPException(status_code=400, detail="Fields domain/source_type/source_location are immutable")
    title = body.get("title")
    tags = body.get("tags")
    metadata = body.get("metadata")
    if tags is not None and not isinstance(tags, list):
        raise HTTPException(status_code=400, detail="tags must be a list of strings")
    if metadata is not None and not isinstance(metadata, dict):
        raise HTTPException(status_code=400, detail="metadata must be an object")
    updated = catalog.update_document(
        document_id,
        title=(title.strip() if isinstance(title, str) else title),
        tags=tags,
        metadata=metadata,
        path=os.getenv("ADMIN_DB_PATH"),
    )
    if not updated:
        # Audit log - not found
        _audit.log_failure(
            action=audit_logger.AuditAction.DOCUMENT_UPDATE,
            reason="document_not_found",
            client_ip=client_ip,
            resource_type="document",
            resource_id=document_id,
            request_id=request_id,
        )
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Audit log
    _audit.log_success(
        action=audit_logger.AuditAction.DOCUMENT_UPDATE,
        client_ip=client_ip,
        resource_type="document",
        resource_id=document_id,
        details={
            "title_updated": bool(title),
            "tags_updated": bool(tags),
            "metadata_updated": bool(metadata),
        },
        request_id=request_id,
    )
    return updated


@router.delete("/documents/{document_id}")
def delete_document_detail(document_id: str, request: Request) -> dict[str, Any]:
    _admin_guard(request)
    client_ip = _get_client_ip(request)
    request_id = _get_request_id(request)
    
    ok = catalog.delete_document(document_id, path=os.getenv("ADMIN_DB_PATH"))
    if not ok:
        # Audit log - not found
        _audit.log_failure(
            action=audit_logger.AuditAction.DOCUMENT_DELETE,
            reason="document_not_found",
            client_ip=client_ip,
            resource_type="document",
            resource_id=document_id,
            request_id=request_id,
        )
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Audit log
    _audit.log_success(
        action=audit_logger.AuditAction.DOCUMENT_DELETE,
        client_ip=client_ip,
        resource_type="document",
        resource_id=document_id,
        request_id=request_id,
    )
    return {"deleted": True}


@router.get("/ingestions")
def list_all_ingestions_endpoint(
    request: Request,
    document_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    since: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
) -> dict[str, Any]:
    _admin_guard(request)
    if document_id and not status and not since:
        runs = catalog.list_ingestions(document_id=document_id, path=os.getenv("ADMIN_DB_PATH"))
    else:
        runs = catalog.list_all_ingestions(
            document_id=document_id,
            status=status,
            since=since,
            limit=limit,
            path=os.getenv("ADMIN_DB_PATH"),
        )
    return {"ingestions": runs}


@router.post("/upload")
async def admin_upload(
    request: Request,
    file: UploadFile = File(...),  # noqa: B008 - FastAPI pattern for required file field
    ingest: bool = Query(default=False),
    document_id: Optional[str] = Query(default=None),
    domain: Optional[str] = Query(default=None),
    title: Optional[str] = Query(default=None),
    tags: Optional[str] = Query(default=None),  # JSON array as string
    metadata: Optional[str] = Query(default=None),  # JSON object as string
) -> dict[str, Any]:
    _admin_guard(request)
    upload_dir = _ensure_upload_dir()
    base_name = os.path.basename(file.filename or "upload.bin")
    try:
        import uuid as _uuid
        safe_name = f"{_uuid.uuid4().hex}-{base_name}"
        dest_path = os.path.join(upload_dir, safe_name)
        size = 0
        with open(dest_path, "wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
                size += len(chunk)
    except Exception as exc:  # pragma: no cover - filesystem hazards
        _logger.error("Upload failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to save upload: {exc}") from exc

    # Guess source type by extension / mime
    try:
        import mimetypes as _m
        mime = file.content_type or _m.guess_type(dest_path)[0]
    except Exception:
        mime = file.content_type or None
    ext = os.path.splitext(base_name)[1].lower()
    guess: str | None
    if ext == ".pdf" or (mime and "pdf" in mime):
        guess = "pdf"
    elif ext in {".docx", ".doc"} or (mime and ("word" in mime or "officedocument" in mime)):
        guess = "docx"
    elif ext in {".md", ".markdown"} or (mime and "markdown" in mime):
        guess = "markdown"
    else:
        guess = None

    info = {
        "path": dest_path,
        "filename": base_name,
        "size_bytes": size,
        "mime": mime,
        "source_type_guess": guess,
    }

    if not ingest:
        return info

    # Optional creation of a document, then trigger ingestion
    parsed_tags: list[str] | None = None
    parsed_meta: dict[str, Any] | None = None
    if tags:
        try:
            import json as _json
            t = _json.loads(tags)
            if not isinstance(t, list):
                raise ValueError("tags must be a JSON array")
            parsed_tags = [str(x) for x in t]
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid tags: {exc}") from exc
    if metadata:
        try:
            import json as _json
            m = _json.loads(metadata)
            if not isinstance(m, dict):
                raise ValueError("metadata must be a JSON object")
            parsed_meta = {str(k): str(v) for k, v in m.items() if v is not None}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid metadata: {exc}") from exc

    db_path = os.getenv("ADMIN_DB_PATH")
    if not document_id:
        if not domain:
            raise HTTPException(
                status_code=400,
                detail="domain is required when creating a document",
            )
        created = catalog.create_document(
            domain=domain.strip(),
            source_type=(guess or "markdown"),
            source_location=dest_path,
            title=(title.strip() if isinstance(title, str) and title.strip() else base_name),
            tags=parsed_tags,
            metadata=parsed_meta,
            path=db_path,
        )
        document_id = created["id"]

    # Trigger ingestion via the existing endpoint/function
    assert isinstance(document_id, str)
    try:
        _ = ingest_document(document_id, request)
    except HTTPException:
        raise
    except Exception as exc:
        _logger.exception("Admin upload-triggered ingest failed")
        raise HTTPException(status_code=500, detail=f"Ingestion trigger failed: {exc}") from exc

    return info
