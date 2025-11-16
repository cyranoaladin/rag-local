from __future__ import annotations

import io
import os
import tempfile

from fastapi.testclient import TestClient

from src.ingestor.api import app as ingest_app


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def test_admin_guard_requires_token(monkeypatch, tmp_path) -> None:
    # Enforce guard presence and safe DB path
    monkeypatch.setenv("INGESTOR_API_TOKEN", "test-token")
    monkeypatch.setenv("ADMIN_DB_PATH", str(tmp_path / "cat.sqlite"))
    client = TestClient(ingest_app)
    r = client.get("/admin/ingestions")
    assert r.status_code in (401, 403)


essential_doc_payload = {
    "title": "Doc",
    "domain": "lycee",
    "source_type": "markdown",
    "source_location": "/data/uploads/doc.md",
}


def test_admin_crud_and_ingest_flow(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as td:
        os.environ["ADMIN_DB_PATH"] = os.path.join(td, "catalog.sqlite")
        os.environ["ADMIN_UPLOAD_DIR"] = os.path.join(td, "uploads")
        os.makedirs(os.environ["ADMIN_UPLOAD_DIR"], exist_ok=True)

        client = TestClient(ingest_app)

        # Create document
        r = client.post("/admin/documents", headers=_auth(), json=essential_doc_payload)
        assert r.status_code == 200
        doc = r.json()
        did = doc["id"]

        # GET
        r = client.get(f"/admin/documents/{did}", headers=_auth())
        assert r.status_code == 200

        # PATCH
        r = client.patch(
            f"/admin/documents/{did}", headers=_auth(), json={"title": "Doc2", "tags": ["y"]}
        )
        assert r.status_code == 200
        assert r.json()["title"] == "Doc2"

        # Mock POST /ingest call inside admin_api to avoid real network
        class DummyResp:
            status_code = 200
            headers = {"content-type": "application/json"}

            def json(self):
                return {"status": "ok", "added": 3}

            def raise_for_status(self):
                return None

        monkeypatch.setenv("INGESTOR_PORT", "8001")
        monkeypatch.setenv("INGESTOR_API_TOKEN", "test-token")
        monkeypatch.setenv("INGEST_AUTH_TOKEN", "test-token")
        monkeypatch.setenv("CHROMA_REQUEST_TIMEOUT", "5")
        monkeypatch.setenv("OLLAMA_REQUEST_TIMEOUT", "5")

        import src.ingestor.admin_api as admin_module

        monkeypatch.setattr(admin_module.requests, "post", lambda *a, **k: DummyResp())

        # Trigger ingest
        r = client.post(f"/admin/documents/{did}/ingest", headers=_auth())
        assert r.status_code == 200
        body = r.json()
        assert body.get("status") == "ok"

        # DELETE
        r = client.delete(f"/admin/documents/{did}", headers=_auth())
        assert r.status_code == 200
        r = client.get(f"/admin/documents/{did}", headers=_auth())
        assert r.status_code == 404


def test_admin_upload_ingest_false_and_true(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as td:
        os.environ["ADMIN_DB_PATH"] = os.path.join(td, "catalog.sqlite")
        os.environ["ADMIN_UPLOAD_DIR"] = os.path.join(td, "uploads")
        os.makedirs(os.environ["ADMIN_UPLOAD_DIR"], exist_ok=True)

        client = TestClient(ingest_app)

        # Prepare a small markdown file in memory
        content = b"# Test"
        files = {"file": ("t.md", io.BytesIO(content), "text/markdown")}

        # Upload only
        r = client.post("/admin/upload?ingest=false&domain=lycee", headers=_auth(), files=files)
        assert r.status_code == 200
        data = r.json()
        assert data["path"].startswith(os.environ["ADMIN_UPLOAD_DIR"])  # saved

        # Patch admin_api.requests.post to simulate success when ingest=true
        class DummyResp:
            status_code = 200
            headers = {"content-type": "application/json"}

            def json(self):
                return {"status": "ok", "added": 1}

            def raise_for_status(self):
                return None

        import src.ingestor.admin_api as admin_module

        monkeypatch.setattr(admin_module.requests, "post", lambda *a, **k: DummyResp())

        r = client.post(
            "/admin/upload?ingest=true&domain=lycee&title=T",
            headers=_auth(),
            files=files,
        )
        assert r.status_code == 200

        # List global ingestions (should be >= 0; exact count not enforced here)
        r = client.get("/admin/ingestions?limit=10", headers=_auth())
        assert r.status_code == 200
        assert isinstance(r.json().get("ingestions"), list)
