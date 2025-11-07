from __future__ import annotations

from importlib import import_module
from typing import Any

import pytest

from tests.test_admin_router_basic import _load_app


class _StubCollection:
    def query(self, query_texts, n_results):  # type: ignore[override]
        return {
            "documents": [["result body" for _ in range(n_results)]],
            "metadatas": [[{"source": "stub"} for _ in range(n_results)]],
            "ids": [[f"doc-{index}" for index in range(n_results)]],
            "distances": [[0.1 for _ in range(n_results)]],
        }


def _prepare_search_env(monkeypatch: pytest.MonkeyPatch, tmp_path, rate_limit: str = "10") -> tuple[Any, str, Any]:
    client, api_key = _load_app(monkeypatch, tmp_path, rate_limit=rate_limit)
    search_api = import_module("src.ingestor.search_api")
    monkeypatch.setattr(search_api, "_collection", lambda name: _StubCollection())
    return client, api_key, search_api


def test_kb_search_origin_forbidden(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    client, api_key, _ = _prepare_search_env(monkeypatch, tmp_path)
    headers = {"X-API-Key": api_key, "Origin": "https://forbidden.example"}
    response = client.post(
        "/kb/search",
        json={"q": "hello"},
        headers=headers,
    )
    assert response.status_code == 403


def test_kb_search_rate_limit(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    client, api_key, _ = _prepare_search_env(monkeypatch, tmp_path, rate_limit="1")
    headers = {"X-API-Key": api_key, "Origin": "https://ops.example.com"}
    ok_response = client.post("/kb/search", json={"q": "ok"}, headers=headers)
    assert ok_response.status_code == 200
    limited = client.post("/kb/search", json={"q": "again"}, headers=headers)
    assert limited.status_code == 429


def test_kb_search_reranker_toggle(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    client, api_key, search_api = _prepare_search_env(monkeypatch, tmp_path)
    calls: list[list[tuple[str, str]]] = []

    class DummyReranker:
        def predict(self, pairs):  # type: ignore[override]
            calls.append(list(pairs))
            return [0.9 for _ in pairs]

    monkeypatch.setattr(search_api, "_ensure_reranker", lambda: DummyReranker())
    search_api.RERANKER_ENABLED = True

    headers = {"X-API-Key": api_key, "Origin": "https://ops.example.com"}
    response = client.post(
        "/kb/search",
        json={"q": "rerank me", "rerank": True},
        headers=headers,
    )
    assert response.status_code == 200
    assert calls, "reranker should have been invoked"

    search_api.RERANKER_ENABLED = False
    calls.clear()
    client.post(
        "/kb/search",
        json={"q": "no rerank", "rerank": False},
        headers=headers,
    )
    assert not calls
