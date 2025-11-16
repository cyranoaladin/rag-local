from __future__ import annotations

import importlib
import sys

import pytest

try:
    from fastapi.testclient import TestClient
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("fastapi is required") from exc


def _load_api(monkeypatch: pytest.MonkeyPatch):
    mod = "src.ingestor.api"
    for m in list(sys.modules):
        if m.startswith("src.ingestor"):
            sys.modules.pop(m)
    monkeypatch.setenv("INGESTOR_API_TOKEN", "tok")
    return importlib.import_module(mod)


def test_ingest_skip_existing(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api(monkeypatch)

    # prepare a single doc via loader
    monkeypatch.setattr(api, "_load_source_documents", lambda req: [api.Document(page_content="hello", metadata={"source":"unit"})])

    class FakeCollection:
        def __init__(self):
            self._ids = []
        def get(self, ids=None, **_):
            return {"ids": ids or []}
        def add(self, **_):
            pytest.fail("should not add when ids already exist")

    class FakeClient:
        def get_or_create_collection(self, *_, **__):
            return FakeCollection()

    monkeypatch.setattr(api, "get_chroma_client", lambda: FakeClient())
    monkeypatch.setattr(api, "TimedOllamaEmbeddings", lambda *a, **k: type("E", (), {"embed_documents": lambda _s, docs: [[0.0] * 3 for _ in docs]})())

    client = TestClient(api.app)
    r = client.post("/ingest", json={"source_type":"markdown","source":"x.md"}, headers={"Authorization":"Bearer tok"})
    assert r.status_code == 200
    body = r.json()
    assert body.get("status") == "ok"
    assert body.get("added") == 0
    assert body.get("skipped") >= 1


def test_ingest_embedding_404(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api(monkeypatch)
    monkeypatch.setattr(api, "_load_source_documents", lambda req: [api.Document(page_content="world", metadata={"source":"unit"})])

    class FakeCollection:
        def get(self, ids=None, **_):
            return {"ids": []}
        def add(self, **_):
            return None

    class FakeClient:
        def get_or_create_collection(self, *_, **__):
            return FakeCollection()

    class BadEmb:
        def __init__(self, *a, **k):
            pass
        def embed_documents(self, docs):
            raise ValueError("HTTP code: 404 not found")

    monkeypatch.setattr(api, "get_chroma_client", lambda: FakeClient())
    # swap TimedOllamaEmbeddings to raise 404 behavior
    monkeypatch.setattr(api, "TimedOllamaEmbeddings", BadEmb)

    client = TestClient(api.app)
    r = client.post("/ingest", json={"source_type":"markdown","source":"x.md"}, headers={"Authorization":"Bearer tok"})
    assert r.status_code == 503


def test_ingest_video_in_text_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api(monkeypatch)
    client = TestClient(api.app)
    r = client.post("/ingest?mode=text", json={"source_type":"video","source":"/data/uploads/v.mp4"}, headers={"Authorization":"Bearer tok"})
    assert r.status_code == 400