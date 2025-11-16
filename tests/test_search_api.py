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


def test_search_success(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api(monkeypatch)

    class FakeCollection:
        def query(self, query_embeddings=None, n_results=6):  # noqa: ARG002
            return {
                "ids": [["id1", "id2"]],
                "documents": [["doc1", "doc2"]],
                "metadatas": [[{"source": "s1"}, {"source": "s2"}]],
                "distances": [[0.1, 0.2]],
            }

    class FakeClient:
        def get_or_create_collection(self, *_, **__):
            return FakeCollection()

    class Emb:
        def __init__(self, *a, **k):
            pass
        def embed_query(self, q):  # noqa: ARG002
            return [0.0, 1.0, 2.0]

    monkeypatch.setattr(api, "get_chroma_client", lambda: FakeClient())
    monkeypatch.setattr(api, "TimedOllamaEmbeddings", Emb)

    client = TestClient(api.app)
    r = client.post(
        "/search",
        json={"q": "hello", "k": 3, "include_documents": True, "collection": api.COLLECTION_NAME},
        headers={"Authorization": "Bearer tok"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("k") == 3
    assert len(body.get("hits", [])) == 2
    assert body["hits"][0]["metadata"]["source"] == "s1"


def test_search_embedding_404(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api(monkeypatch)

    class FakeCollection:
        def query(self, **_):
            pytest.fail("should not query when embedding fails")

    class FakeClient:
        def get_or_create_collection(self, *_, **__):
            return FakeCollection()

    class BadEmb:
        def __init__(self, *a, **k):
            pass
        def embed_query(self, q):  # noqa: ARG002
            raise ValueError("HTTP code: 404 not found")

    monkeypatch.setattr(api, "get_chroma_client", lambda: FakeClient())
    monkeypatch.setattr(api, "TimedOllamaEmbeddings", BadEmb)

    client = TestClient(api.app)
    r = client.post(
        "/search",
        json={"q": "x"},
        headers={"Authorization": "Bearer tok"},
    )
    assert r.status_code == 503
