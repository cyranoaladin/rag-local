from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

try:
    from fastapi.testclient import TestClient
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("fastapi is required") from exc


def _load_api(monkeypatch: pytest.MonkeyPatch, pre_env: dict[str, str] | None = None):
    mod = "src.ingestor.api"
    for m in list(sys.modules):
        if m.startswith("src.ingestor"):
            sys.modules.pop(m)
    monkeypatch.setenv("INGESTOR_API_TOKEN", "tok")
    for k, v in (pre_env or {}).items():
        monkeypatch.setenv(k, v)
    return importlib.import_module(mod)


def test_ingest_empty_chunks_returns_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api(monkeypatch)

    # Simulate whitespace-only document → no eligible chunks
    monkeypatch.setattr(api, "_load_source_documents", lambda req: [api.Document(page_content="   ", metadata={})])

    class FakeCollection:
        def get(self, ids=None, **_):
            return {"ids": []}
        def add(self, **_):
            return None

    class FakeClient:
        def get_or_create_collection(self, *_, **__):
            return FakeCollection()

    monkeypatch.setattr(api, "get_chroma_client", lambda: FakeClient())
    monkeypatch.setattr(api, "TimedOllamaEmbeddings", lambda *a, **k: type("E", (), {"embed_documents": lambda _s, docs: [[0.0] * 3 for _ in docs]})())

    client = TestClient(api.app)
    r = client.post("/ingest", json={"source_type":"markdown","source":"x.md"}, headers={"Authorization":"Bearer tok"})
    assert r.status_code == 200
    assert "Aucun contenu" in r.json().get("message", "")


def test_authorization_raw_header(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    api = _load_api(monkeypatch, pre_env={"LOCAL_SOURCE_ROOT": str(tmp_path)})
    # Prepare a small markdown file to ensure success path
    f = tmp_path / "a.md"
    f.write_text("hello", encoding="utf-8")

    class FakeCollection:
        def get(self, ids=None, **_):
            return {"ids": []}
        def add(self, **_):
            return None

    class FakeClient:
        def get_or_create_collection(self, *_, **__):
            return FakeCollection()

    monkeypatch.setattr(api, "get_chroma_client", lambda: FakeClient())
    monkeypatch.setattr(api, "TimedOllamaEmbeddings", lambda *a, **k: type("E", (), {"embed_documents": lambda _s, docs: [[0.0] * 3 for _ in docs]})())

    client = TestClient(api.app)
    r = client.post("/ingest", json={"source_type":"markdown","source": f.name}, headers={"Authorization":"tok"})
    assert r.status_code == 200


def test_local_path_outside_root_forbidden(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    api = _load_api(monkeypatch, pre_env={"LOCAL_SOURCE_ROOT": str(tmp_path)})
    client = TestClient(api.app)
    # Use an absolute path outside of LOCAL_SOURCE_ROOT
    outside = "/etc/hosts"
    r = client.post("/ingest", json={"source_type":"markdown","source": outside}, headers={"Authorization":"Bearer tok"})
    assert r.status_code == 400


def test_metrics_404_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _load_api(monkeypatch)
    # Ensure metrics disabled branch is covered
    api.ingest_metrics.METRICS_ENABLED = False
    client = TestClient(api.app)
    r = client.get("/metrics")
    assert r.status_code == 404