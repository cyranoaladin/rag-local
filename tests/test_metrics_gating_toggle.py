from __future__ import annotations

import importlib
import sys

from fastapi.testclient import TestClient


def _reload_app(monkeypatch, enabled: str) -> tuple[object, object]:
    monkeypatch.setenv("METRICS_ENABLED", enabled)
    for name in ("src.ingestor.metrics", "src.ingestor.api"):
        sys.modules.pop(name, None)
    metrics = importlib.import_module("src.ingestor.metrics")
    api = importlib.import_module("src.ingestor.api")
    return metrics, api


def test_metrics_endpoint_enabled(monkeypatch) -> None:
    _, api = _reload_app(monkeypatch, "true")
    client = TestClient(api.app)
    response = client.get("/metrics")
    assert response.status_code == 200
    assert b"ingest_requests_total" in response.content


def test_metrics_endpoint_disabled(monkeypatch) -> None:
    _, api = _reload_app(monkeypatch, "false")
    client = TestClient(api.app)
    response = client.get("/metrics")
    assert response.status_code == 404
