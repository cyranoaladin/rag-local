from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

try:
    from fastapi.testclient import TestClient
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("fastapi is required for tests") from exc


def _load_api(monkeypatch: pytest.MonkeyPatch, pre_env: dict[str, str] | None = None):
    # Ensure a clean import for api module with desired env
    module_name = "src.ingestor.api"
    for mod in list(sys.modules):
        if mod.startswith("src.ingestor"):
            sys.modules.pop(mod)
    # set env before import so module-level constants pick them up
    monkeypatch.setenv("INGESTOR_API_TOKEN", "tok")
    monkeypatch.delenv("INGESTOR_IP_ALLOWLIST", raising=False)
    for k, v in (pre_env or {}).items():
        monkeypatch.setenv(k, v)
    return importlib.import_module(module_name)


def test_admin_endpoints_cover(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    api = _load_api(monkeypatch, pre_env={"ADMIN_UPLOAD_DIR": str(tmp_path)})
    client = TestClient(api.app)
    # /admin/health should be ok
    r = client.get("/admin/health")
    assert r.status_code == 200
    # /admin/reindex should be 503 (not configured)
    r = client.post("/admin/reindex")
    assert r.status_code == 503


def test_helpers_cover(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api(monkeypatch)
    # normalize_metadata drops empty and normalizes keys
    out = api.normalize_metadata({" A ": "x", "": "", "k e y": "v", "none": None})
    assert out == {"a": "x", "k_e_y": "v"}
    # content hash stable
    h1 = api.get_content_hash("abc")
    h2 = api.get_content_hash("abc")
    assert h1 == h2 and len(h1) == 64


def test_ingest_markdown_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Prepare a markdown file
    md = tmp_path / "note.md"
    md.write_text("# Title\n\nHello world!", encoding="utf-8")

    api = _load_api(monkeypatch, pre_env={"LOCAL_SOURCE_ROOT": str(tmp_path)})

    # Fake Chroma collection and client
    added_ids: list[str] = []

    class FakeCollection:
        def get(self, ids=None, **_):
            return {"ids": []}

        def add(self, documents=None, ids=None, metadatas=None, embeddings=None):
            _ = documents, metadatas, embeddings
            added_ids.extend(ids or [])

    class FakeClient:
        def get_or_create_collection(self, *_, **__):
            return FakeCollection()

    class FakeEmbeddings:
        def __init__(self, *_a, **_k):
            pass

        def embed_documents(self, docs):
            # return one vector per doc
            return [[0.1, 0.2, 0.3] for _ in docs]

    monkeypatch.setattr(api, "get_chroma_client", lambda: FakeClient())
    # Replace TimedOllamaEmbeddings if present
    if hasattr(api, "TimedOllamaEmbeddings"):
        monkeypatch.setattr(api, "TimedOllamaEmbeddings", FakeEmbeddings)
    else:
        monkeypatch.setattr(api, "OllamaEmbeddings", FakeEmbeddings)

    client = TestClient(api.app)

    headers = {"Authorization": "Bearer tok", "Content-Type": "application/json"}
    payload = {"source_type": "markdown", "source": md.name, "hints": {"x": "y"}}
    r = client.post("/ingest", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("status") == "ok"
    # at least one id was added
    assert len(added_ids) >= 1