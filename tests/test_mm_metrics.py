import importlib
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_metrics import _install_dependency_stubs


def _reload_ingestor_app():
    _install_dependency_stubs()
    import src.ingestor.metrics as metrics
    import src.ingestor.mm_adapter as mm_adapter
    import src.ingestor.api as api

    metrics = importlib.reload(metrics)
    mm_adapter = importlib.reload(mm_adapter)
    api = importlib.reload(api)
    return api, metrics, mm_adapter


def _prepare_common_stubs(api, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    dummy_file = tmp_path / "sample.pdf"
    dummy_file.write_text("dummy content", encoding="utf-8")

    monkeypatch.setattr(api, "_resolve_local_path", lambda path: dummy_file, raising=False)

    class DummyCollection:
        def get(self, ids):
            return {"ids": []}

        def add(self, **kwargs):
            return None

    class DummyClient:
        def __init__(self, *args, **kwargs):
            pass

        def get_or_create_collection(self, **kwargs):
            return DummyCollection()

    monkeypatch.setattr(api.chromadb, "HttpClient", lambda *args, **kwargs: DummyClient(), raising=False)

    class DummyEmbeddings:
        def __init__(self, *args, **kwargs):
            pass

        def embed_documents(self, docs):
            return [[1.0] for _ in docs]

    monkeypatch.setattr(api, "OllamaEmbeddings", DummyEmbeddings, raising=False)


def test_mm_adapter_emits_metrics_per_chunk(monkeypatch, tmp_path):
    monkeypatch.setenv("METRICS_ENABLED", "true")
    monkeypatch.setenv("METRICS_NAMESPACE", "rag_local")
    monkeypatch.setenv("MULTIMODAL_ENABLED", "true")

    api, metrics, mm_adapter = _reload_ingestor_app()
    if not getattr(api, "MULTIMODAL_ENABLED", False):
        pytest.skip("Multimodal mode disabled")
    _prepare_common_stubs(api, monkeypatch, tmp_path)

    def fake_parse(file, filename, mime, **kwargs):
        with metrics.track_mm_parse_latency():
            chunks = [
                mm_adapter.Chunk(modality="text", text="alpha", metadata={"chunk_index": "0"}),
                mm_adapter.Chunk(modality="image", blob=b"123456", metadata={"chunk_index": "1"}),
                mm_adapter.Chunk(modality="table", text="table-row", metadata={"chunk_index": "2"}),
            ]
        for chunk in chunks:
            size = chunk.approx_bytes()
            metrics.record_mm_chunk(chunk.modality, size if size else len(chunk.as_text().encode("utf-8")))
            yield chunk

    monkeypatch.setattr(api, "parse_multimodal", fake_parse)

    client = TestClient(api.app)
    response = client.post(
        "/ingest?mode=multimodal",
        json={"source_type": "pdf", "source": "dummy.pdf"},
    )
    assert response.status_code == 200

    metrics_response = client.get("/metrics")
    body = metrics_response.text
    assert 'rag_local_mm_chunks_total{modality="text"} 1.0' in body
    assert 'rag_local_mm_chunks_total{modality="image"} 1.0' in body
    assert 'rag_local_mm_chunks_total{modality="table"} 1.0' in body
    assert 'rag_local_mm_bytes_total{modality="image"}' in body
    assert 'rag_local_mm_bytes_total{modality="text"}' in body
    assert 'rag_local_mm_bytes_total{modality="table"}' in body


def test_mm_latency_histogram_updates(monkeypatch, tmp_path):
    monkeypatch.setenv("METRICS_ENABLED", "true")
    monkeypatch.setenv("METRICS_NAMESPACE", "rag_local")
    monkeypatch.setenv("MULTIMODAL_ENABLED", "true")

    api, metrics, mm_adapter = _reload_ingestor_app()
    if not getattr(api, "MULTIMODAL_ENABLED", False):
        pytest.skip("Multimodal mode disabled")

    handle = io.BytesIO(b"hello world")
    list(
        mm_adapter.parse_multimodal(
            handle,
            filename="sample.txt",
            mime="text/plain",
            timeout_s=1,
            max_chars_per_chunk=16,
            cache_dir=str(tmp_path),
        )
    )

    body = metrics.generate_latest(metrics.REGISTRY).decode("utf-8")
    assert "rag_local_mm_parse_latency_seconds_count 1.0" in body


def test_mm_timeout_counts_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("METRICS_ENABLED", "true")
    monkeypatch.setenv("METRICS_NAMESPACE", "rag_local")
    monkeypatch.setenv("MULTIMODAL_ENABLED", "true")
    monkeypatch.setenv("MM_PARSER_TIMEOUT", "0")

    api, metrics, mm_adapter = _reload_ingestor_app()
    if not getattr(api, "MULTIMODAL_ENABLED", False):
        pytest.skip("Multimodal mode disabled")
    _prepare_common_stubs(api, monkeypatch, tmp_path)

    client = TestClient(api.app)
    response = client.post(
        "/ingest?mode=multimodal",
        json={"source_type": "pdf", "source": "dummy.pdf"},
    )
    assert response.status_code == 200

    metrics_response = client.get("/metrics")
    assert metrics_response.status_code == 200
    assert 'rag_local_mm_parse_failures_total{reason="timeout"} 1.0' in metrics_response.text
