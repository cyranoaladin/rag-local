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
    # reload to apply env each time
    for m in list(sys.modules):
        if m.startswith("src.ingestor"):
            sys.modules.pop(m)
    return importlib.import_module(mod)


def _patch_ok_search(monkeypatch, api):
    class FakeCollection:
        def query(self, query_embeddings=None, n_results=6):  # noqa: ARG002
            return {
                "ids": [["a"]],
                "documents": [["d"]],
                "metadatas": [[{"source": "s"}]],
                "distances": [[0.5]],
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


def test_search_allowed_with_loopback_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INGESTOR_API_TOKEN", "tok")
    monkeypatch.setenv("INGESTOR_IP_ALLOWLIST", "127.0.0.1/32")
    api = _load_api(monkeypatch)
    _patch_ok_search(monkeypatch, api)
    client = TestClient(api.app)
    r = client.post(
        "/search",
        json={"q": "x", "k": 1, "include_documents": False, "collection": api.COLLECTION_NAME},
        headers={"Authorization": "Bearer tok", "X-Forwarded-For": "127.0.0.1"},
    )
    assert r.status_code == 200


def test_search_blocked_with_forwarded_ip_outside_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INGESTOR_API_TOKEN", "tok")
    monkeypatch.setenv("INGESTOR_IP_ALLOWLIST", "127.0.0.1/32")
    api = _load_api(monkeypatch)
    _patch_ok_search(monkeypatch, api)
    client = TestClient(api.app)
    r = client.post(
        "/search",
        json={"q": "x"},
        headers={"X-API-Token": "tok", "X-Forwarded-For": "192.168.1.55"},
    )
    assert r.status_code == 403


def test_search_generic_embedding_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INGESTOR_API_TOKEN", "tok")
    api = _load_api(monkeypatch)

    class FakeCollection:
        def get(self, *a, **k):  # pragma: no cover
            return {}

        def query(self, *a, **k):  # pragma: no cover
            return {}

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
        "/search",
        json={"q": "x"},
        headers={"Authorization": "Bearer tok"},
    )
    assert r.status_code == 500
