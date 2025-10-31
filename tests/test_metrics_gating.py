from fastapi.testclient import TestClient

from src.ingestor import metrics as ingest_metrics
from src.ingestor.api import app


def test_metrics_enabled_returns_200(monkeypatch):
    monkeypatch.setattr(ingest_metrics, "METRICS_ENABLED", True, raising=False)
    client = TestClient(app)
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.text.startswith("# HELP") or "ingest_" in response.text


def test_metrics_disabled_returns_404(monkeypatch):
    monkeypatch.setattr(ingest_metrics, "METRICS_ENABLED", False, raising=False)
    client = TestClient(app)
    response = client.get("/metrics")
    assert response.status_code == 404
