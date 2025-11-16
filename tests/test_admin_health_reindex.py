from __future__ import annotations

import os
import tempfile

from fastapi.testclient import TestClient

from src.ingestor.api import app as ingest_app


def test_admin_health_ok(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("ADMIN_DB_PATH", os.path.join(td, "catalog.sqlite"))
        monkeypatch.setenv("ADMIN_UPLOAD_DIR", os.path.join(td, "uploads"))
        client = TestClient(ingest_app)
        r = client.get("/admin/health")
        assert r.status_code == 200
        assert r.json().get("status") in ("ok", "healthy")


def test_admin_reindex_placeholder(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("ADMIN_DB_PATH", os.path.join(td, "catalog.sqlite"))
        monkeypatch.setenv("ADMIN_UPLOAD_DIR", os.path.join(td, "uploads"))
        client = TestClient(ingest_app)
        r = client.post("/admin/reindex")
        assert r.status_code == 503
