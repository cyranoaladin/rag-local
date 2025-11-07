"""Prometheus metrics helpers for ingest services."""

# -----------------------------------------------------------------------------
# Metrics Contract (documentation only)
# -----------------------------------------------------------------------------
# - This service exposes a single CollectorRegistry via ``REGISTRY``.
#   ALL counters/histograms must register against THIS instance (not the global
#   registry). That preserves per-process isolation and predictable scrape
#   surfaces in tests.
#
# - Gating par ``METRICS_ENABLED`` :
#   * By default metrics stay ENABLED until the environment variable is set to
#     ``false`` explicitly.
#   * The ``/metrics`` endpoint MUST return 404 when disabled.
#   * Metric helper functions MUST no-op when disabled.
#
# - Namespace guidance:
#   * ``METRICS_NAMESPACE`` scopes all families (e.g. ``rag_*``).
#   * Counters/histograms should always pass ``registry=REGISTRY``.
#
# - Tests:
#   * Tests can monkeypatch ``ingest_metrics.METRICS_ENABLED`` to steer
#     ``/metrics`` behaviour without re-importing the module.
#   * This documentation block introduces zero functional changes.
# -----------------------------------------------------------------------------

from __future__ import annotations

import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import TypeVar, cast

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

__all__ = [
    "METRICS_ENABLED",
    "REGISTRY",
    "generate_latest",
    "REQUEST_COUNT",
    "REQUEST_LATENCY",
    "INGEST_RESULT",
    "ingest_requests_total",
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
    "get_admin_metrics",
    "get_kb_metrics",
    "get_job_event_metrics",
    "record_job_event",
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

_admin_metric_cache: dict[int, tuple[Counter, Counter, Histogram]] = {}
_kb_metric_cache: dict[int, tuple[Counter, Counter, Histogram]] = {}
_job_event_cache: dict[int, Counter] = {}


def get_admin_metrics() -> tuple[Counter, Counter, Histogram]:
    registry_id = id(REGISTRY)
    cached = _admin_metric_cache.get(registry_id)
    if cached is not None:
        return cached
    requests = Counter(
        "admin_requests_total",
        "Admin API requests",
        ("route", "method", "code", "tenant"),
        registry=REGISTRY,
    )
    failures = Counter(
        "admin_failures_total",
        "Admin API failures",
        ("route", "tenant", "reason"),
        registry=REGISTRY,
    )
    latency = Histogram(
        "admin_latency_seconds",
        "Latency for admin API operations",
        ("route",),
        registry=REGISTRY,
    )
    bundle = (requests, failures, latency)
    _admin_metric_cache[registry_id] = bundle
    return bundle


def get_kb_metrics() -> tuple[Counter, Counter, Histogram]:
    registry_id = id(REGISTRY)
    cached = _kb_metric_cache.get(registry_id)
    if cached is not None:
        return cached
    requests = Counter(
        "kb_search_requests_total",
        "Knowledge base search requests",
        ("route", "method", "code", "tenant"),
        registry=REGISTRY,
    )
    failures = Counter(
        "kb_search_failures_total",
        "Knowledge base search failures",
        ("route", "tenant", "reason"),
        registry=REGISTRY,
    )
    latency = Histogram(
        "kb_search_latency_seconds",
        "Latency for KB endpoints",
        ("route",),
        registry=REGISTRY,
    )
    bundle = (requests, failures, latency)
    _kb_metric_cache[registry_id] = bundle
    return bundle


def get_job_event_metrics() -> Counter:
    registry_id = id(REGISTRY)
    cached = _job_event_cache.get(registry_id)
    if cached is not None:
        return cached
    events = Counter(
        "jobs_events_total",
        "Total job events streamed via SSE",
        ("tenant", "level"),
        registry=REGISTRY,
    )
    _job_event_cache[registry_id] = events
    return events

if "REQUEST_COUNT" not in globals():
    REQUEST_COUNT = Counter(
        "ingestor_requests_total",
        "Total requests",
        ("path", "method", "code"),
        registry=REGISTRY,
    )

if "REQUEST_LATENCY" not in globals():
    REQUEST_LATENCY = Histogram(
        "ingestor_request_latency_seconds",
        "Request latency",
        ("path", "method"),
        registry=REGISTRY,
    )

if "INGEST_RESULT" not in globals():
    INGEST_RESULT = Counter(
        "ingestor_ingest_events_total",
        "Ingest events",
        ("status",),
        registry=REGISTRY,
    )

if "ingest_requests_total" not in globals():
    ingest_requests_total = Counter(
        "ingest_requests_total",
        "Ingest request outcomes by source and modality",
        ("source", "modality", "status"),
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


@_guarded
def record_job_event(tenant: str, level: str) -> None:
    safe_tenant = (tenant or "unknown").strip().lower() or "unknown"
    safe_level = (level or "info").strip().lower() or "info"
    get_job_event_metrics().labels(tenant=safe_tenant, level=safe_level).inc()
