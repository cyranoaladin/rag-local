from __future__ import annotations

import logging
import os
from typing import Any

import requests
from fastapi import APIRouter, HTTPException, Request, Query
from pydantic import BaseModel, Field

try:
    from . import catalog as catalog
except Exception:  # pragma: no cover - executed when running as top-level module
    import catalog as catalog

router = APIRouter(prefix="/admin", tags=["admin"])
_logger = logging.getLogger(__name__)


# --- Security: reuse same token as /ingest (Bearer or X-API-Token) ---

def _admin_guard(request: Request) -> None:
    token_env = os.getenv("INGESTOR_API_TOKEN") or os.getenv("INGEST_AUTH_TOKEN")
    if not token_env:
        return  # no guard configured
    header_token = request.headers.get("X-API-Token") or request.headers.get("x-api-token")
    if not header_token:
        auth = request.headers.get("Authorization") or request.headers.get("authorization")
        if isinstance(auth, str) and auth.strip():
            value = auth.strip()
            header_token = value.split(" ", 1)[1].strip() if value.lower().startswith("bearer ") else value
    if header_token != token_env:
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
    """Basic readiness probe for admin integrations."""
    _admin_guard(request)
    _ensure_upload_dir()
    catalog.init_db(os.getenv("ADMIN_DB_PATH"))
    return {"status": "ok"}


# --- Catalog models ---

class CreateDocumentPayload(BaseModel):
    domain: str = Field(description="lycee | web3 | ...")
    title: str | None = None
    source_type: str = Field(description="url|gdrive_folder|pdf|docx|markdown|md|video")
    source_location: str
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None


@router.post("/documents")
def create_document(payload: CreateDocumentPayload, request: Request) -> dict[str, Any]:
    _admin_guard(request)
    doc = catalog.create_document(
        domain=payload.domain.strip(),
        source_type=payload.source_type.strip(),
        source_location=payload.source_location.strip(),
        title=(payload.title.strip() if payload.title else None),
        tags=[t.strip() for t in (payload.tags or []) if t and t.strip()],
        metadata=payload.metadata or {},
        path=os.getenv("ADMIN_DB_PATH"),
    )
    return doc


@router.get("/documents")
def list_documents(domain: str | None = Query(default=None), request: Request | None = None) -> dict[str, Any]:
    if request is not None:
        _admin_guard(request)
    docs = catalog.list_documents(domain=domain.strip() if domain else None, path=os.getenv("ADMIN_DB_PATH"))
    return {"documents": docs}


@router.get("/documents/{document_id}/ingestions")
def list_doc_ingestions(document_id: str, request: Request) -> dict[str, Any]:
    _admin_guard(request)
    runs = catalog.list_ingestions(document_id=document_id, path=os.getenv("ADMIN_DB_PATH"))
    return {"ingestions": runs}


@router.post("/documents/{document_id}/ingest")
def ingest_document(document_id: str, request: Request) -> dict[str, Any]:
    _admin_guard(request)
    db_path = os.getenv("ADMIN_DB_PATH")
    doc = catalog.get_document(document_id, path=db_path)
    if not doc:
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
        resp = requests.post(f"{base_url}/ingest", json=ingest_payload, timeout=60, headers=headers)
        resp.raise_for_status()
        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        added = int(body.get("added", 0)) if isinstance(body, dict) else 0
        catalog.finish_ingestion_run(run["id"], status="success", error_message=None, chunks_count=added, path=db_path)
        return {"status": "ok", "run": run, "result": body}
    except Exception as exc:
        catalog.finish_ingestion_run(run["id"], status="error", error_message=str(exc), chunks_count=None, path=db_path)
        raise HTTPException(status_code=500, detail=f"Admin ingest failed: {exc}") from exc


@router.post("/reindex")
def trigger_reindex(payload: dict[str, Any] | None = None, request: Request | None = None) -> dict[str, str]:
    """Placeholder endpoint for batch reindex orchestration.

    The actual implementation is environment-specific; for now we acknowledge the
    call so that automation hooks can validate connectivity.
    """
    if request is not None:
        _admin_guard(request)
    _ = payload
    _ensure_upload_dir()
    _logger.info("Received reindex request via admin API")
    raise HTTPException(status_code=503, detail="Reindexing backend not configured")
