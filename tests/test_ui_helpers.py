from __future__ import annotations

import importlib
import sys
import types
from typing import Any

import pytest


def _import_app(monkeypatch: pytest.MonkeyPatch):
    """Import `src.ui.app` without triggering the Streamlit render."""
    monkeypatch.setenv("STREAMLIT_IMPORT_ONLY", "1")
    if "streamlit" not in sys.modules:
        streamlit_stub = types.ModuleType("streamlit")
        streamlit_stub.session_state = {}
        sys.modules["streamlit"] = streamlit_stub
    if "src.ui.app" in sys.modules:
        del sys.modules["src.ui.app"]
    return importlib.import_module("src.ui.app")


def test_api_headers_with_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """_api_headers includes X-API-Token when INGEST_API_TOKEN is set."""
    monkeypatch.setenv("INGEST_API_TOKEN", "my-token")
    app = _import_app(monkeypatch)
    headers = app._api_headers()
    assert headers == {"X-API-Token": "my-token"}


def test_api_headers_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """_api_headers returns empty dict when no token is configured."""
    monkeypatch.delenv("INGEST_API_TOKEN", raising=False)
    monkeypatch.delenv("INGESTOR_API_TOKEN", raising=False)
    app = _import_app(monkeypatch)
    headers = app._api_headers()
    assert headers == {}


def test_api_get_calls_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    """api_get makes a GET request with auth headers."""
    monkeypatch.setenv("INGEST_API_TOKEN", "tok")
    monkeypatch.setenv("INGEST_BASE_URL", "http://ingestor:8001")
    app = _import_app(monkeypatch)

    captured: dict[str, Any] = {}

    class DummyResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"collections": []}

    def fake_get(url: str, headers: dict[str, str], timeout: float, **_: Any):
        captured.update({"url": url, "headers": headers, "timeout": timeout})
        return DummyResponse()

    monkeypatch.setattr(app.requests, "get", fake_get)

    result = app.api_get("/collections", timeout=10.0)
    assert result == {"collections": []}
    assert captured["url"] == "http://ingestor:8001/collections"
    assert captured["headers"] == {"X-API-Token": "tok"}


def test_api_post_calls_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    """api_post makes a POST request with auth headers and payload."""
    monkeypatch.setenv("INGEST_API_TOKEN", "tok")
    monkeypatch.setenv("INGEST_BASE_URL", "http://ingestor:8001")
    app = _import_app(monkeypatch)

    captured: dict[str, Any] = {}

    class DummyResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"hits": []}

    def fake_post(url: str, json: dict[str, Any], headers: dict[str, str], timeout: float, **_: Any):
        captured.update({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return DummyResponse()

    monkeypatch.setattr(app.requests, "post", fake_post)

    result = app.api_post("/search", {"q": "test", "k": 5}, timeout=10.0)
    assert result == {"hits": []}
    assert captured["url"] == "http://ingestor:8001/search"
    assert captured["json"] == {"q": "test", "k": 5}
    assert captured["headers"] == {"X-API-Token": "tok"}


def test_build_search_payload_includes_optional_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _import_app(monkeypatch)

    payload = app._build_search_payload(
        query="suites",
        k=6,
        include_documents=False,
        collection="rag_maths_premiere",
        filters={"matiere": "Maths"},
        score_threshold=0.42,
    )

    assert payload == {
        "q": "suites",
        "k": 6,
        "include_documents": False,
        "collection": "rag_maths_premiere",
        "filters": {"matiere": "Maths"},
        "score_threshold": 0.42,
    }


def test_build_search_payload_omits_empty_optional_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _import_app(monkeypatch)

    payload = app._build_search_payload(
        query="suites",
        k=6,
        include_documents=True,
        collection="",
        filters={},
        score_threshold=None,
    )

    assert payload == {
        "q": "suites",
        "k": 6,
        "include_documents": True,
    }
