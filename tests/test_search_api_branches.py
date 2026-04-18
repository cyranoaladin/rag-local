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


def test_search_no_distances(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api(monkeypatch)

    class FakeCollection:
        def query(self, query_embeddings=None, n_results=6):  # noqa: ARG002
            return {
                "ids": [["id1"]],
                "documents": [["doc1"]],
                "metadatas": [[{"source": "s1"}]],
                # distances intentionally missing to take the false branch
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
        "/search",
        json={"q": "hi", "k": 1, "include_documents": False, "collection": api.COLLECTION_NAME},
        headers={"Authorization": "Bearer tok"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body.get("k") == 1
    assert len(body.get("hits", [])) == 1
    # No score key because distances missing
    assert "score" not in body["hits"][0]
