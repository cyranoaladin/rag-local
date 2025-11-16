import re

from fastapi.testclient import TestClient

from src.ingestor.api import app


def test_metrics_endpoint_exposes_counters(monkeypatch):
    monkeypatch.setenv("METRICS_ENABLED", "true")
    # Certains modules peuvent avoir déjà lu la config, on force aussi côté module
    try:
        import src.ingestor.metrics as metrics_mod
        metrics_mod.METRICS_ENABLED = True
    except ImportError:
        pass
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code in (200, 204)

    metrics_response = client.get("/metrics")
    assert metrics_response.status_code == 200
    body = metrics_response.text
    assert "ingestor_requests_total" in body
    assert "ingestor_request_latency_seconds_bucket" in body
    assert re.search(r"ingestor_ingest_events_total", body)
