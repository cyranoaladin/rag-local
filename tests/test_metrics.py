import importlib
import sys
import types

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


def _reload_app() -> FastAPI:
    _install_dependency_stubs()
    import src.ingestor.metrics as metrics
    import src.ingestor.api as api

    importlib.reload(metrics)
    importlib.reload(api)
    return api.app


def _install_dependency_stubs() -> None:
    if "docx" not in sys.modules:
        docx_module = types.ModuleType("docx")

        class _DocxDocument:  # pragma: no cover - stub only
            def __init__(self, *args, **kwargs):
                raise RuntimeError("docx stub used in tests")

        docx_module.Document = _DocxDocument
        sys.modules["docx"] = docx_module

    if "langchain_community" not in sys.modules:
        loaders_module = types.ModuleType("langchain_community.document_loaders")

        class _DummyLoader:  # pragma: no cover - stub only
            def __init__(self, *args, **kwargs):
                raise RuntimeError("langchain stub used in tests")

        loaders_module.PyPDFLoader = _DummyLoader
        sys.modules["langchain_community.document_loaders"] = loaders_module

        embeddings_module = types.ModuleType("langchain_community.embeddings")

        class _DummyEmbeddings:  # pragma: no cover - stub only
            def __init__(self, *args, **kwargs):
                raise RuntimeError("langchain stub used in tests")

        embeddings_module.OllamaEmbeddings = _DummyEmbeddings
        sys.modules["langchain_community.embeddings"] = embeddings_module

        root_module = types.ModuleType("langchain_community")
        root_module.__path__ = []
        root_module.document_loaders = loaders_module
        root_module.embeddings = embeddings_module
        sys.modules["langchain_community"] = root_module

    if "langchain_core" not in sys.modules:
        documents_module = types.ModuleType("langchain_core.documents")

        class _DummyDocument:  # pragma: no cover - stub only
            def __init__(self, *args, **kwargs):
                raise RuntimeError("langchain stub used in tests")

        documents_module.Document = _DummyDocument
        sys.modules["langchain_core.documents"] = documents_module

        core_module = types.ModuleType("langchain_core")
        core_module.__path__ = []
        core_module.documents = documents_module
        sys.modules["langchain_core"] = core_module

    if "langchain_google_community" not in sys.modules:
        google_module = types.ModuleType("langchain_google_community")

        class _DummyGDriveLoader:  # pragma: no cover - stub only
            def __init__(self, *args, **kwargs):
                raise RuntimeError("langchain stub used in tests")

            def load(self):
                raise RuntimeError("langchain stub used in tests")

        google_module.GoogleDriveLoader = _DummyGDriveLoader
        sys.modules["langchain_google_community"] = google_module

    if "langchain_text_splitters" not in sys.modules:
        splitter_module = types.ModuleType("langchain_text_splitters")

        class _DummySplitter:  # pragma: no cover - stub only
            def __init__(self, *args, **kwargs):
                raise RuntimeError("langchain stub used in tests")

            def split_documents(self, *args, **kwargs):
                raise RuntimeError("langchain stub used in tests")

        splitter_module.RecursiveCharacterTextSplitter = _DummySplitter
        sys.modules["langchain_text_splitters"] = splitter_module

    if "chromadb" not in sys.modules:
        chroma_module = types.ModuleType("chromadb")

        class _DummyClient:  # pragma: no cover - stub only
            def __init__(self, *args, **kwargs):
                raise RuntimeError("chromadb stub used in tests")

        chroma_module.HttpClient = _DummyClient
        sys.modules["chromadb"] = chroma_module


def test_metrics_enabled(monkeypatch):
    monkeypatch.setenv("METRICS_ENABLED", "true")
    monkeypatch.setenv("METRICS_NAMESPACE", "rag_local")
    app = _reload_app()

    client = TestClient(app)
    metrics_response = client.get("/metrics")
    assert metrics_response.status_code == 200
    assert b"rag_local_ingest_requests_total" in metrics_response.content


def test_metrics_disabled(monkeypatch):
    monkeypatch.setenv("METRICS_ENABLED", "false")
    monkeypatch.delenv("METRICS_NAMESPACE", raising=False)
    app = _reload_app()

    client = TestClient(app)
    metrics_response = client.get("/metrics")
    assert metrics_response.status_code == 404


def test_ingest_success_increments_counters(monkeypatch):
    monkeypatch.setenv("METRICS_ENABLED", "true")
    monkeypatch.setenv("METRICS_NAMESPACE", "rag_local")
    app = _reload_app()

    import src.ingestor.api as api

    payload_doc = types.SimpleNamespace(page_content="Hello chunk", metadata={"page": 1})

    class DummySplitter:
        def __init__(self, *args, **kwargs):
            pass

        def split_documents(self, docs):
            return [payload_doc]

    class DummyCollection:
        def get(self, ids):
            return {"ids": []}

        def add(self, documents, ids, metadatas, embeddings):
            return None

    class DummyClient:
        def get_or_create_collection(self, name, metadata):
            return DummyCollection()

    class DummyEmbeddings:
        def __init__(self, *args, **kwargs):
            pass

        def embed_documents(self, documents):
            return [[0.1] for _ in documents]

    monkeypatch.setattr(api, "load_from_url", lambda url: [payload_doc])
    monkeypatch.setattr(api, "RecursiveCharacterTextSplitter", DummySplitter)
    monkeypatch.setattr(api.chromadb, "HttpClient", lambda host, port: DummyClient())
    monkeypatch.setattr(api, "OllamaEmbeddings", DummyEmbeddings)

    client = TestClient(app)
    response = client.post(
        "/ingest",
        json={"source_type": "url", "source": "https://example.com"},
    )
    assert response.status_code == 200

    metrics_response = client.get("/metrics")
    assert metrics_response.status_code == 200
    body = metrics_response.text
    assert 'rag_local_ingest_success_total{modality="text"} 1.0' in body
    assert 'rag_local_ingest_chunks_total{modality="text"} 1.0' in body


def test_ingest_failure_increments_reason(monkeypatch):
    monkeypatch.setenv("METRICS_ENABLED", "true")
    monkeypatch.setenv("METRICS_NAMESPACE", "rag_local")
    app = _reload_app()

    import src.ingestor.api as api

    def _raise_unsupported(url: str):
        raise HTTPException(status_code=415, detail="Unsupported MIME")

    monkeypatch.setattr(api, "load_from_url", _raise_unsupported)

    client = TestClient(app)
    response = client.post(
        "/ingest",
        json={"source_type": "url", "source": "https://example.com"},
    )
    assert response.status_code == 415

    metrics_response = client.get("/metrics")
    assert metrics_response.status_code == 200
    assert 'rag_local_ingest_failure_total{reason="unsupported_mime"} 1.0' in metrics_response.text
