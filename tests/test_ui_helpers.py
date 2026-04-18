from __future__ import annotations

import importlib
import sys
from typing import Any

import pytest


def _import_app(monkeypatch: pytest.MonkeyPatch):
    """Import `src.ui.app` without triggering the Streamlit render."""
    monkeypatch.setenv("STREAMLIT_IMPORT_ONLY", "1")
    if "src.ui.app" in sys.modules:
        del sys.modules["src.ui.app"]
    return importlib.import_module("src.ui.app")


def test_call_ingest_api_success_with_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _import_app(monkeypatch)

    class DummyResponse:
        status_code = 200

        def __init__(self, body: dict[str, Any]):
            self._body = body

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return self._body

    captured: dict[str, Any] = {}

    def fake_post(
        url: str,
        params: dict[str, Any],
        json: dict[str, Any],
        headers: dict[str, str],
        timeout: float,
        **_: Any,
    ):
        captured.update({
            "url": url,
            "params": params,
            "json": json,
            "headers": headers,
            "timeout": timeout,
        })
        return DummyResponse({"status": "ok"})

    monkeypatch.setattr(app.requests, "post", fake_post)

    result = app._call_ingest_api(
        "http://ingestor:8001",
        "tok",
        {"source": "/data/uploads/foo.pdf", "source_type": "pdf"},
        "text",
    )

    assert result == {"status": "ok"}
    assert captured["url"] == "http://ingestor:8001/ingest"
    assert captured["params"] == {"mode": "text"}
    assert captured["headers"] == {"Content-Type": "application/json", "Authorization": "Bearer tok"}
    assert captured["timeout"] == app.INGEST_TIMEOUT


def test_call_ingest_api_requires_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _import_app(monkeypatch)
    with pytest.raises(ValueError):
        app._call_ingest_api(None, None, {}, "text")
