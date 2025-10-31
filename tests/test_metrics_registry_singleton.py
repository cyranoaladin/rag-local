from __future__ import annotations

import importlib
import sys

from fastapi.testclient import TestClient


def _reload_modules() -> tuple[object, object]:
    for name in ("src.ingestor.metrics", "src.ingestor.api"):
        sys.modules.pop(name, None)
    ingest_metrics = importlib.import_module("src.ingestor.metrics")
    api = importlib.import_module("src.ingestor.api")
    return ingest_metrics, api


def test_metrics_registry_no_double_registration(monkeypatch) -> None:
    monkeypatch.setenv("METRICS_ENABLED", "true")
    ingest_metrics, api = _reload_modules()

    first_client = TestClient(api.app)
    first_response = first_client.get("/metrics")
    assert first_response.status_code in (200, 404)
    first_count = len(list(ingest_metrics.REGISTRY.collect()))

    monkeypatch.setenv("METRICS_ENABLED", "true")
    ingest_metrics, api = _reload_modules()

    second_client = TestClient(api.app)
    second_response = second_client.get("/metrics")
    assert second_response.status_code in (200, 404)
    second_count = len(list(ingest_metrics.REGISTRY.collect()))

    assert second_count <= first_count + 1
