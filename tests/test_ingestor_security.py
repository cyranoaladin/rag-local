# pylint: disable=line-too-long,too-many-statements
from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

import pytest

try:
    from fastapi.testclient import TestClient
except ImportError as exc:  # pragma: no cover - hard fail when fastapi missing
    raise RuntimeError(
        "Required module 'fastapi' is missing for tests. Install dev dependencies with `pip install -r requirements-dev.txt`."
    ) from exc


def ensure_dependency_stubs() -> None:
    """Provide lightweight stand-ins for heavy optional dependencies."""

    def ensure_module(name: str, builder) -> types.ModuleType:
        if name in sys.modules:
            return sys.modules[name]
        module = builder()
        if not hasattr(module, "__spec__") or module.__spec__ is None:
            module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None)
        sys.modules[name] = module
        return module

    def make_package(name: str) -> types.ModuleType:
        module = types.ModuleType(name)
        module.__path__ = []  # mark as package for import machinery
        module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, is_package=True)
        return module

    if importlib.util.find_spec("chromadb") is None:
        def build_chromadb():
            module = types.ModuleType("chromadb")

            class _DummyClient:
                def __init__(self, *_args, **_kwargs):
                    pass

                def get_or_create_collection(self, *_args, **_kwargs):
                    raise RuntimeError("chromadb stub in tests; monkeypatch expected")

            module.HttpClient = _DummyClient
            return module

        ensure_module("chromadb", build_chromadb)
        def build_chromadb_config():
            module = types.ModuleType("chromadb.config")

            class _DummySettings:
                def __init__(self, *_args, **_kwargs):
                    pass

            module.Settings = _DummySettings
            return module

        ensure_module("chromadb.config", build_chromadb_config)

    if importlib.util.find_spec("docx") is None:
        def build_docx():
            module = types.ModuleType("docx")
            module.__spec__ = importlib.machinery.ModuleSpec("docx", loader=None)

            class _DummyDocument:
                def __init__(self, *_args, **_kwargs):
                    self.paragraphs = []

            module.Document = _DummyDocument
            return module

        ensure_module("docx", build_docx)

    if importlib.util.find_spec("bs4") is None:
        def build_bs4():
            module = types.ModuleType("bs4")
            module.__spec__ = importlib.machinery.ModuleSpec("bs4", loader=None)

            class _DummySoup:
                def __init__(self, html: str, _parser: str = "html.parser"):
                    self._html = html

                def get_text(self, separator: str = " ", strip: bool = False) -> str:
                    text = self._html
                    if strip:
                        text = text.strip()
                    return separator.join(text.split())

            module.BeautifulSoup = _DummySoup
            return module

        ensure_module("bs4", build_bs4)

    if importlib.util.find_spec("langchain_community") is None:
        ensure_module("langchain_community", lambda: make_package("langchain_community"))

    if importlib.util.find_spec("langchain_community.document_loaders") is None:
        parent = ensure_module("langchain_community", lambda: make_package("langchain_community"))

        def build_doc_loaders():
            module = types.ModuleType("langchain_community.document_loaders")

            class _DummyLoader:
                def __init__(self, *_args, **_kwargs):
                    pass

                def load(self):
                    raise RuntimeError("loader stub used in tests")

            module.PyPDFLoader = _DummyLoader
            return module

        submodule = ensure_module("langchain_community.document_loaders", build_doc_loaders)
        setattr(parent, "document_loaders", submodule)  # noqa: B010 - test stub wiring

    if importlib.util.find_spec("langchain_community.embeddings") is None:
        parent = ensure_module("langchain_community", lambda: make_package("langchain_community"))

        def build_embeddings():
            module = types.ModuleType("langchain_community.embeddings")

            class _DummyEmbeddings:
                def __init__(self, *_args, **_kwargs):
                    pass

                def embed_documents(self, documents):
                    return [[0.0] * 3 for _ in documents]

            module.OllamaEmbeddings = _DummyEmbeddings
            return module

        submodule = ensure_module("langchain_community.embeddings", build_embeddings)
        setattr(parent, "embeddings", submodule)  # noqa: B010 - test stub wiring

    if importlib.util.find_spec("langchain_core") is None:
        ensure_module("langchain_core", lambda: make_package("langchain_core"))

    if importlib.util.find_spec("langchain_core.documents") is None:
        parent = ensure_module("langchain_core", lambda: make_package("langchain_core"))

        def build_documents():
            module = types.ModuleType("langchain_core.documents")

            class _DummyDocument:
                def __init__(self, page_content: str, metadata: dict | None = None):
                    self.page_content = page_content
                    self.metadata = metadata or {}

            module.Document = _DummyDocument
            return module

        submodule = ensure_module("langchain_core.documents", build_documents)
        setattr(parent, "documents", submodule)  # noqa: B010 - test stub wiring

    if importlib.util.find_spec("langchain_google_community") is None:
        def build_google():
            module = types.ModuleType("langchain_google_community")

            class _DummyLoader:
                def __init__(self, *_args, **_kwargs):
                    pass

                def load(self):
                    raise RuntimeError("Google loader stub used in tests")

            module.GoogleDriveLoader = _DummyLoader
            return module

        ensure_module("langchain_google_community", build_google)

    if importlib.util.find_spec("langchain_text_splitters") is None:
        def build_splitter():
            module = types.ModuleType("langchain_text_splitters")

            class _DummySplitter:
                def __init__(self, *_args, **_kwargs):
                    pass

                def split_documents(self, documents):
                    return documents

            module.RecursiveCharacterTextSplitter = _DummySplitter
            return module

        ensure_module("langchain_text_splitters", build_splitter)


def reload_api(monkeypatch: pytest.MonkeyPatch, token: str | None, allowlist: str | None = None) -> Any:
    """Reload the ingestor module with test-specific configuration."""
    ensure_dependency_stubs()
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    module_name = "src.ingestor.api"
    monkeypatch.setenv("HTTP_TIMEOUT", "0.1")
    monkeypatch.setenv("USER_AGENT", "pytest-agent")
    if token is None:
        monkeypatch.delenv("INGESTOR_API_TOKEN", raising=False)
        monkeypatch.delenv("INGEST_AUTH_TOKEN", raising=False)
    else:
        monkeypatch.setenv("INGESTOR_API_TOKEN", token)
    if allowlist is None:
        monkeypatch.delenv("INGESTOR_IP_ALLOWLIST", raising=False)
    else:
        monkeypatch.setenv("INGESTOR_IP_ALLOWLIST", allowlist)
    # Ensure module reload picks up new environment variables.
    metrics_module = "src.ingestor.metrics"
    if metrics_module in list(sys.modules):
        sys.modules.pop(metrics_module)
    if module_name in list(sys.modules):
        sys.modules.pop(module_name)
    return importlib.import_module(module_name)


def test_ingest_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    api = reload_api(monkeypatch, token="super-secret")
    client = TestClient(api.app)

    response = client.post(
        "/ingest",
        json={"source_type": "url", "source": "https://example.com"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Unauthorized"


def test_ingest_accepts_token_and_stores_documents(monkeypatch: pytest.MonkeyPatch) -> None:
    api = reload_api(monkeypatch, token="super-secret")

    # Avoid network I/O during the test.
    dummy_doc = api.Document(page_content="hello", metadata={"original": "test"})
    monkeypatch.setattr(api, "load_from_url", lambda url: [dummy_doc])

    added_payloads: list[list[str]] = []

    class FakeCollection:
        def get(self, ids=None, **_kwargs):
            _ = ids
            return {"ids": []}

        def add(self, documents=None, ids=None, metadatas=None, embeddings=None):
            _ = documents, metadatas, embeddings
            added_payloads.append(list(ids or []))

    fake_collection = FakeCollection()

    class FakeClient:
        def get_or_create_collection(self, *_args, **_kwargs):
            return fake_collection

    class FakeEmbeddings:
        def __init__(self, *_args, **_kwargs):
            _ = _args, _kwargs

        def embed_documents(self, documents):
            return [[0.0] * 3 for _ in documents]

    def fake_client_factory():
        return FakeClient()

    monkeypatch.setattr(api, "get_chroma_client", fake_client_factory)
    monkeypatch.setattr(api, "OllamaEmbeddings", FakeEmbeddings)
    if hasattr(api, "TimedOllamaEmbeddings"):
        monkeypatch.setattr(api, "TimedOllamaEmbeddings", FakeEmbeddings)

    client = TestClient(api.app)
    response = client.post(
        "/ingest",
        headers={"X-API-Token": "super-secret"},
        json={
            "source_type": "url",
            "source": "https://example.com",
            "hints": {"matiere": "NSI"},
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["added"] == 1
    assert added_payloads and len(added_payloads[0]) == 1


def test_ingest_no_token_configured_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    """When INGESTOR_API_TOKEN is not set, all requests are rejected with 503."""
    api = reload_api(monkeypatch, token=None)
    client = TestClient(api.app)

    response = client.post(
        "/ingest",
        json={"source_type": "url", "source": "https://example.com"},
    )

    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_ingest_ip_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    """When IP allowlist is set, requests from disallowed IPs are rejected with 403."""
    api = reload_api(monkeypatch, token="test-token", allowlist="10.0.0.0/8")
    client = TestClient(api.app)

    response = client.post(
        "/ingest",
        json={"source_type": "url", "source": "https://example.com"},
        headers={"X-API-Token": "test-token", "X-Forwarded-For": "1.2.3.4"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Forbidden"


def test_ingest_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bearer token in Authorization header is accepted."""
    api = reload_api(monkeypatch, token="bearer-secret")

    dummy_doc = api.Document(page_content="hello", metadata={"original": "test"})
    monkeypatch.setattr(api, "load_from_url", lambda url: [dummy_doc])

    class FakeCollection:
        def get(self, ids=None, **_kwargs):
            return {"ids": []}

        def add(self, **_kwargs):
            pass

    class FakeClient:
        def get_or_create_collection(self, *_args, **_kwargs):
            return FakeCollection()

    class FakeEmbeddings:
        def __init__(self, *_args, **_kwargs):
            pass

        def embed_documents(self, documents):
            return [[0.0] * 3 for _ in documents]

    monkeypatch.setattr(api, "get_chroma_client", lambda: FakeClient())
    monkeypatch.setattr(api, "OllamaEmbeddings", FakeEmbeddings)
    if hasattr(api, "TimedOllamaEmbeddings"):
        monkeypatch.setattr(api, "TimedOllamaEmbeddings", FakeEmbeddings)

    client = TestClient(api.app)
    response = client.post(
        "/ingest",
        headers={"Authorization": "Bearer bearer-secret"},
        json={"source_type": "url", "source": "https://example.com"},
    )

    assert response.status_code == 200, response.text


def test_health_is_public(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /health should work without any token."""
    api = reload_api(monkeypatch, token="some-secret")
    client = TestClient(api.app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_metrics_is_public(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /metrics remains public for Prometheus scraping."""
    api = reload_api(monkeypatch, token="metrics-secret")
    client = TestClient(api.app)

    response = client.get("/metrics")
    assert response.status_code in {200, 404}

    response = client.get("/metrics", headers={"X-API-Token": "metrics-secret"})
    assert response.status_code in {200, 404}


def test_collections_requires_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /collections requires authentication."""
    api = reload_api(monkeypatch, token="col-secret")
    client = TestClient(api.app)

    response = client.get("/collections")
    assert response.status_code == 401


def test_stats_requires_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /stats/{collection} requires authentication."""
    api = reload_api(monkeypatch, token="stats-secret")
    client = TestClient(api.app)

    response = client.get("/stats/rag_education")
    assert response.status_code == 401
