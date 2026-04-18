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


def test_rag_query_no_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api(monkeypatch)

    class FakeCollection:
        def query(self, **kwargs):  # kwargs contains no 'where'
            assert "where" not in kwargs
            return {
                "ids": [["id1"]],
                "documents": [["d1"]],
                "metadatas": [[{"source": "s1"}]],
                "distances": [[0.42]],
            }

    class FakeClient:
        def get_or_create_collection(self, *_, **__):
            return FakeCollection()

    class Emb:
        def __init__(self, *a, **k):  # noqa: ARG002
            pass

        def embed_query(self, q):  # noqa: ARG002
            return [0.0, 1.0]

    monkeypatch.setattr(api, "get_chroma_client", lambda: FakeClient())
    monkeypatch.setattr(api, "TimedOllamaEmbeddings", Emb)

    client = TestClient(api.app)
    r = client.post(
        "/rag/query",
        json={"query": "q", "top_k": 1, "collection": api.COLLECTION_NAME},
        headers={"Authorization": "Bearer tok"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("k") == 1
    assert len(body.get("hits", [])) == 1


def test_rag_query_generic_embedding_error(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api(monkeypatch)

    class FakeCollection:
        def query(self, **_):
            pytest.fail("should not query when embedding fails")

    class FakeClient:
        def get_or_create_collection(self, *_, **__):
            return FakeCollection()

    class BadEmb:
        def __init__(self, *a, **k):  # noqa: ARG002
            pass

        def embed_query(self, q):  # noqa: ARG002
            raise RuntimeError("boom")

    monkeypatch.setattr(api, "get_chroma_client", lambda: FakeClient())
    monkeypatch.setattr(api, "TimedOllamaEmbeddings", BadEmb)

    client = TestClient(api.app)
    r = client.post(
        "/rag/query",
        json={"query": "x"},
        headers={"Authorization": "Bearer tok"},
    )
    assert r.status_code == 500
