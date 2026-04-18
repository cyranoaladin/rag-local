from __future__ import annotations

import io
import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from src.ingestor.api import app as ingest_app


def _auth() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


@pytest.fixture(autouse=True)
def _admin_env(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("ADMIN_DB_PATH", os.path.join(td, "catalog.sqlite"))
        monkeypatch.setenv("ADMIN_UPLOAD_DIR", os.path.join(td, "uploads"))
        os.makedirs(os.environ["ADMIN_UPLOAD_DIR"], exist_ok=True)
        monkeypatch.setenv("INGESTOR_API_TOKEN", "test-token")
        yield


def test_list_documents_with_domain_filter() -> None:
    client = TestClient(ingest_app)
    # empty list with domain filter
    r = client.get("/admin/documents?domain=lycee", headers=_auth())
    assert r.status_code == 200
    assert r.json().get("documents") == []


def test_ingest_document_not_found() -> None:
    client = TestClient(ingest_app)
    r = client.post("/admin/documents/does-not-exist/ingest", headers=_auth())
    assert r.status_code == 404


def test_update_document_invalid_payload() -> None:
    client = TestClient(ingest_app)
    r = client.patch("/admin/documents/xxx", headers=_auth(), json=["not-a-dict"])  # type: ignore[list-item]
    assert r.status_code == 400


def test_update_document_forbidden_fields() -> None:
    client = TestClient(ingest_app)
    # First create a document to patch against
    payload = {
        "title": "Doc",
        "domain": "lycee",
        "source_type": "markdown",
        "source_location": "/data/uploads/doc.md",
    }
    create = client.post("/admin/documents", headers=_auth(), json=payload)
    assert create.status_code == 200
    did = create.json()["id"]

    r = client.patch(f"/admin/documents/{did}", headers=_auth(), json={"domain": "nope"})
    assert r.status_code == 400


def test_update_document_tags_and_metadata_type_errors() -> None:
    client = TestClient(ingest_app)
    payload = {
        "title": "Doc",
        "domain": "lycee",
        "source_type": "markdown",
        "source_location": "/data/uploads/doc.md",
    }
    create = client.post("/admin/documents", headers=_auth(), json=payload)
    assert create.status_code == 200
    did = create.json()["id"]

    r = client.patch(f"/admin/documents/{did}", headers=_auth(), json={"tags": "oops"})
    assert r.status_code == 400
    r = client.patch(f"/admin/documents/{did}", headers=_auth(), json={"metadata": ["oops"]})
    assert r.status_code == 400


def test_update_unknown_document_returns_404() -> None:
    client = TestClient(ingest_app)
    r = client.patch("/admin/documents/unknown", headers=_auth(), json={"title": "X"})
    assert r.status_code == 404


def test_delete_unknown_document_returns_404() -> None:
    client = TestClient(ingest_app)
    r = client.delete("/admin/documents/missing", headers=_auth())
    assert r.status_code == 404


def test_list_all_ingestions_with_document_id_param() -> None:
    client = TestClient(ingest_app)
    r = client.get("/admin/ingestions?document_id=abc", headers=_auth())
    assert r.status_code == 200
    assert isinstance(r.json().get("ingestions"), list)


def test_admin_upload_source_type_guessing_pdf_docx_md_and_none(monkeypatch) -> None:
    client = TestClient(ingest_app)

    def _upload(name: str, mime: str | None) -> dict:
        content = b"dummy"
        files = {"file": (name, io.BytesIO(content), mime) if mime else (name, io.BytesIO(content))}
        r = client.post("/admin/upload?ingest=false&domain=lycee", headers=_auth(), files=files)
        assert r.status_code == 200
        return r.json()

    info_pdf = _upload("x.pdf", "application/pdf")
    assert info_pdf["source_type_guess"] == "pdf"

    info_docx = _upload("x.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert info_docx["source_type_guess"] == "docx"

    info_md = _upload("x.md", "text/markdown")
    assert info_md["source_type_guess"] == "markdown"

    info_bin = _upload("x.bin", None)
    assert info_bin["source_type_guess"] is None


def test_admin_upload_invalid_tags_and_metadata_json() -> None:
    client = TestClient(ingest_app)
    content = b"# md"
    files = {"file": ("t.md", io.BytesIO(content), "text/markdown")}

    r = client.post("/admin/upload?ingest=true&domain=lycee&tags=not-json", headers=_auth(), files=files)
    assert r.status_code == 400

    r = client.post("/admin/upload?ingest=true&domain=lycee&metadata=not-json", headers=_auth(), files=files)
    assert r.status_code == 400


def test_admin_upload_ingest_exception_is_500(monkeypatch) -> None:
    client = TestClient(ingest_app)

    import src.ingestor.admin_api as admin_module

    # Force document creation; then ingest_document raises a runtime error to hit exception path
    def boom_ingest(*a, **k):  # noqa: ARG002
        raise RuntimeError("boom")

    monkeypatch.setattr(admin_module, "ingest_document", boom_ingest)

    content = b"# md"
    files = {"file": ("t.md", io.BytesIO(content), "text/markdown")}
    r = client.post("/admin/upload?ingest=true&domain=lycee", headers=_auth(), files=files)
    assert r.status_code == 500
