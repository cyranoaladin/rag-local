"""Prometheus metrics helpers for ingest services."""
from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Callable, Iterator, TypeVar, cast

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

__all__ = [
    "METRICS_ENABLED",
    "REGISTRY",
    "generate_latest",
    "record_request",
    "observe_latency",
    "record_success",
    "record_failure",
    "record_chunk",
    "record_bytes",
    "track_latency",
    "track_mm_parse_latency",
    "record_mm_chunk",
    "record_mm_failure",
]

METRICS_ENABLED = os.getenv("METRICS_ENABLED", "true").lower() == "true"
NAMESPACE = os.getenv("METRICS_NAMESPACE", "rag_local")

REGISTRY = CollectorRegistry()

_REQUESTS = Counter(
    f"{NAMESPACE}_ingest_requests_total",
    "Total ingest endpoint requests",
    ("route", "method"),
    registry=REGISTRY,
)
_SUCCESS = Counter(
    f"{NAMESPACE}_ingest_success_total",
    "Successful ingests by modality",
    ("modality",),
    registry=REGISTRY,
)
_FAILURE = Counter(
    f"{NAMESPACE}_ingest_failure_total",
    "Failed ingests by reason",
    ("reason",),
    registry=REGISTRY,
)
_CHUNKS = Counter(
    f"{NAMESPACE}_ingest_chunks_total",
    "Number of chunks stored by modality",
    ("modality",),
    registry=REGISTRY,
)
_BYTES = Counter(
    f"{NAMESPACE}_ingest_bytes_total",
    "Aggregate bytes persisted during ingest",
    registry=REGISTRY,
)
_LATENCY = Histogram(
    f"{NAMESPACE}_ingest_latency_seconds",
    "Latency observed per ingest route",
    ("route",),
    buckets=(0.1, 0.3, 0.6, 1.0, 2.5, 5.0),
    registry=REGISTRY,
)

_MM_LATENCY = Histogram(
    f"{NAMESPACE}_mm_parse_latency_seconds",
    "Latency observed during multimodal parsing",
    buckets=(0.1, 0.3, 0.6, 1.0, 2.5, 5.0),
    registry=REGISTRY,
)
_MM_CHUNKS = Counter(
    f"{NAMESPACE}_mm_chunks_total",
    "Number of multimodal chunks emitted by modality",
    ("modality",),
    registry=REGISTRY,
)
_MM_BYTES = Counter(
    f"{NAMESPACE}_mm_bytes_total",
    "Bytes processed while emitting multimodal chunks",
    ("modality",),
    registry=REGISTRY,
)
_MM_FAILURES = Counter(
    f"{NAMESPACE}_mm_parse_failures_total",
    "Multimodal parse failures by reason",
    ("reason",),
    registry=REGISTRY,
)


F = TypeVar("F", bound=Callable[..., object])


def _guarded(func: F) -> F:
    def wrapper(*args, **kwargs):
        if not METRICS_ENABLED:
            return None
        return func(*args, **kwargs)

    return cast(F, wrapper)


@_guarded
def record_request(route: str, method: str) -> None:
    _REQUESTS.labels(route=route, method=method).inc()


@_guarded
def observe_latency(route: str, seconds: float) -> None:
    _LATENCY.labels(route=route).observe(seconds)


@_guarded
def record_success(modality: str) -> None:
    _SUCCESS.labels(modality=modality).inc()


@_guarded
def record_failure(reason: str) -> None:
    _FAILURE.labels(reason=reason).inc()


@_guarded
def record_chunk(modality: str) -> None:
    _CHUNKS.labels(modality=modality).inc()


@_guarded
def record_bytes(amount: int) -> None:
    if amount < 0:
        return
    _BYTES.inc(amount)


@contextmanager
def track_latency(route: str) -> Iterator[None]:
    if not METRICS_ENABLED:
        yield
        return
    with _LATENCY.labels(route=route).time():
        yield


def _normalize_modality(modality: str) -> str:
    normalized = (modality or "").strip().lower()
    if normalized in {"text", "image", "table", "formula"}:
        return normalized
    return "other"


@contextmanager
def track_mm_parse_latency() -> Iterator[None]:
    if not METRICS_ENABLED:
        yield
        return
    with _MM_LATENCY.time():
        yield


@_guarded
def record_mm_chunk(modality: str, nbytes: int) -> None:
    safe_modality = _normalize_modality(modality)
    _MM_CHUNKS.labels(modality=safe_modality).inc()
    if nbytes > 0:
        _MM_BYTES.labels(modality=safe_modality).inc(nbytes)


@_guarded
def record_mm_failure(reason: str) -> None:
    safe_reason = (reason or "unknown").strip().lower().replace(" ", "_")
    if not safe_reason:
        safe_reason = "unknown"
    _MM_FAILURES.labels(reason=safe_reason).inc()
