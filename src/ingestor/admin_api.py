from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/admin", tags=["admin"])
_logger = logging.getLogger(__name__)


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
def admin_health() -> dict[str, str]:
    """Basic readiness probe for admin integrations."""
    _ensure_upload_dir()
    return {"status": "ok"}


@router.post("/reindex")
def trigger_reindex(payload: dict[str, Any] | None = None) -> dict[str, str]:
    """Placeholder endpoint for batch reindex orchestration.

    The actual implementation is environment-specific; for now we acknowledge the
    call so that automation hooks can validate connectivity.
    """
    _ = payload
    _ensure_upload_dir()
    _logger.info("Received reindex request via admin API")
    raise HTTPException(status_code=503, detail="Reindexing backend not configured")
