"""Server-Sent Events helpers for streaming admin job events."""
from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import TYPE_CHECKING

from src.ingestor import metrics as ingest_metrics

if TYPE_CHECKING:
    from src.admin.service import AdminService, JobEvent


def _serialize_event(event: JobEvent) -> dict[str, str]:
    payload = {
        "id": str(event.id),
        "job_id": event.job_id,
        "level": event.level,
        "message": event.message,
    }
    timestamp = getattr(event, "timestamp", None)
    if timestamp is not None:
        payload["timestamp"] = timestamp.isoformat()
    return payload


def _encode_sse(event_id: int | None, event_type: str, data: dict[str, str]) -> bytes:
    parts: list[str] = []
    if event_id is not None:
        parts.append(f"id: {event_id}")
    parts.append(f"event: {event_type}")
    parts.append(f"data: {json.dumps(data, ensure_ascii=False)}")
    parts.append("")
    return ("\n".join(parts) + "\n").encode("utf-8")


def stream_job_events(
    service: AdminService,
    job_id: str,
    tenant: str,
    *,
    poll_interval: float = 1.0,
    heartbeat_interval: float = 15.0,
) -> Iterator[bytes]:
    """Yield job events as SSE-formatted byte chunks."""

    events = service.list_job_events(job_id)
    if not events:
        yield _encode_sse(None, "keepalive", {"job_id": job_id})
        return

    last_emitted = time.monotonic()
    for event in events:
        ingest_metrics.record_job_event(tenant, event.level)
        data = _serialize_event(event)
        yield _encode_sse(event.id, "message", data)
        last_emitted = time.monotonic()

    if time.monotonic() - last_emitted >= heartbeat_interval:
        yield _encode_sse(None, "keepalive", {"job_id": job_id})