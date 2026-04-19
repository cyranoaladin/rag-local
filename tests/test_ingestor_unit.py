# pylint: disable=too-many-locals,line-too-long
from __future__ import annotations

import sys
import tempfile
import types
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.test_ingestor_security import reload_api


class _DummySplitter:
    def split_documents(self, documents):
        return documents


class _RequestStub:
    def __init__(self, headers: dict[str, str], host: str = "127.0.0.1") -> None:
        self.headers = headers
        self.client = types.SimpleNamespace(host=host)


def _setup_success_stubs(api_module, monkeypatch: pytest.MonkeyPatch, documents: list[Any]) -> None:
    monkeypatch.setattr(api_module, "load_from_url", lambda _: documents)

    class FakeCollection:
        def __init__(self) -> None:
            self.add_calls: list[tuple[list[str], list[str], list[dict[str, Any]]]] = []

        def get(self, ids=None, **_kwargs):
            _ = ids
            return {"ids": []}

        def add(self, documents=None, ids=None, metadatas=None, embeddings=None):
            _ = embeddings
            self.add_calls.append((list(documents or []), list(ids or []), list(metadatas or [])))

    fake_collection = FakeCollection()

    class FakeClient:
        def get_or_create_collection(self, *_args, **_kwargs):
            return fake_collection

    class FakeEmbeddings:
        def __init__(self, *_args, **_kwargs):
            pass

        def embed_documents(self, docs):
            return [[0.1] * 3 for _ in docs]

    monkeypatch.setattr(api_module, "get_chroma_client", lambda: FakeClient())
    monkeypatch.setattr(api_module, "TimedOllamaEmbeddings", FakeEmbeddings)
    monkeypatch.setattr(api_module, "OllamaEmbeddings", FakeEmbeddings)
    return fake_collection


def test_enforce_security_accepts_valid_token_and_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    api = reload_api(monkeypatch, token="super-secret", allowlist="127.0.0.0/8")
    request = _RequestStub(headers={"X-API-Token": "super-secret", "x-forwarded-for": ""})

    api._enforce_security(request, None)


def test_enforce_security_rejects_bad_token(monkeypatch: pytest.MonkeyPatch) -> None:
    api = reload_api(monkeypatch, token="super-secret", allowlist="127.0.0.0/8")
    request = _RequestStub(headers={"X-API-Token": "invalid", "x-forwarded-for": ""})

    with pytest.raises(api.HTTPException) as exc:
        api._enforce_security(request, None)

    assert exc.value.status_code == 401


def test_prepare_chunks_for_chroma_preserves_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    api = reload_api(monkeypatch, token=None)
    req = api.IngestRequest(source_type="url", source="https://example.com", metadata_hints={"matiere": "NSI"})
    document = api.Document(page_content="Hello world", metadata={"mime_type": "text/html", "page": 1})

    prepared = api._prepare_chunks_for_chroma(req, [document], splitter=_DummySplitter())

    assert prepared.ids and len(prepared.ids) == 1
    assert prepared.documents[0] == "Hello world"
    assert prepared.metadatas[0]["source"] == "https://example.com"
    assert prepared.metadatas[0]["modality"] == "text"
    assert prepared.metadatas[0]["matiere"] == "NSI"
    assert prepared.modality == "text"


def test_ingest_text_endpoint_success(monkeypatch: pytest.MonkeyPatch) -> None:
    api = reload_api(monkeypatch, token="super-secret")
    doc = api.Document(page_content="content", metadata={"mime_type": "text/plain"})
    fake_collection = _setup_success_stubs(api, monkeypatch, [doc])

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

    assert response.status_code == 200
    payload = response.json()
    assert payload["added"] == 1
    assert fake_collection.add_calls and len(fake_collection.add_calls[0][1]) == 1


def test_ingest_accepts_camel_case_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    tmp_upload_dir = tempfile.mkdtemp(prefix="admin-uploads-")
    monkeypatch.setenv("ADMIN_UPLOAD_DIR", tmp_upload_dir)
    monkeypatch.setenv("LOCAL_SOURCE_ROOT", tmp_upload_dir)
    api = reload_api(monkeypatch, token="token")
    doc = api.Document(page_content="alias", metadata={"mime_type": "text/plain"})
    _ = _setup_success_stubs(api, monkeypatch, [doc])

    client = TestClient(api.app)
    response = client.post(
        "/ingest",
        headers={"X-API-Token": "token"},
        json={
            "sourceType": "url",
            "sourceUrl": "https://example.com",
            "metadata": {"matiere": "Maths"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["added"] == 1


def test_metrics_counter_updates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("METRICS_ENABLED", "true")
    api = reload_api(monkeypatch, token="super-secret")
    doc = api.Document(page_content="metrics doc", metadata={"mime_type": "text/plain"})
    _ = _setup_success_stubs(api, monkeypatch, [doc])

    client = TestClient(api.app)
    success_child = api.ingest_requests_total.labels(source="url", modality="text", status="success")
    failure_child = api.ingest_requests_total.labels(source="url", modality="unknown", status="http_401")

    assert success_child._value.get() == 0
    assert failure_child._value.get() == 0

    ok_response = client.post(
        "/ingest",
        headers={"X-API-Token": "super-secret"},
        json={"source_type": "url", "source": "https://example.com"},
    )
    assert ok_response.status_code == 200
    assert success_child._value.get() == 1

    ko_response = client.post(
        "/ingest",
        json={"source_type": "url", "source": "https://example.com"},
    )
    assert ko_response.status_code == 401
    assert failure_child._value.get() == 1


def test_admin_router_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    api = reload_api(monkeypatch, token="admin-token")
    registered_paths = {route.path for route in api.app.routes}
    assert any(path.startswith("/admin") for path in registered_paths)


def test_load_docx_prefers_unstructured(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    api = reload_api(monkeypatch, token=None)
    target = tmp_path / "sample.docx"
    target.write_bytes(b"")

    class FakeMeta:
        def to_dict(self) -> dict[str, Any]:
            return {"page_number": 2, "section": "table"}

    class FakeElement:
        def __init__(self) -> None:
            self.text = "Table cell"
            self.metadata = FakeMeta()

    def fake_partition_docx(filename: str, include_metadata: bool = True):
        assert filename == str(target)
        assert include_metadata is True
        return [FakeElement()]

    package = types.ModuleType("unstructured")
    package.__path__ = []
    subpackage = types.ModuleType("unstructured.partition")
    subpackage.__path__ = []
    docx_module = types.ModuleType("unstructured.partition.docx")
    docx_module.partition_docx = fake_partition_docx

    monkeypatch.setitem(sys.modules, "unstructured", package)
    monkeypatch.setitem(sys.modules, "unstructured.partition", subpackage)
    monkeypatch.setitem(sys.modules, "unstructured.partition.docx", docx_module)

    documents = api.load_docx(str(target))
    assert len(documents) == 1
    doc = documents[0]
    assert doc.page_content == "Table cell"
    assert doc.metadata["page_number"] == "2"
    assert doc.metadata["source"] == target.name
    assert doc.metadata["mime_type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_search_filters_hits_by_score_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    api = reload_api(monkeypatch, token="search-token")

    class FakeCollection:
        def query(self, **_kwargs):
            return {
                "documents": [["bon hit", "mauvais hit"]],
                "metadatas": [[{"source": "a.pdf"}, {"source": "b.pdf"}]],
                "ids": [["hit-a", "hit-b"]],
                "distances": [[0.12, 0.81]],
            }

    class FakeClient:
        def get_or_create_collection(self, *_args, **_kwargs):
            return FakeCollection()

    class FakeEmbeddings:
        def __init__(self, *_args, **_kwargs):
            pass

        def embed_query(self, _query):
            return [0.1, 0.2, 0.3]

    monkeypatch.setattr(api, "get_chroma_client", lambda: FakeClient())
    monkeypatch.setattr(api, "TimedOllamaEmbeddings", FakeEmbeddings)

    client = TestClient(api.app)
    response = client.post(
        "/search",
        headers={"X-API-Token": "search-token"},
        json={
            "q": "suites",
            "k": 5,
            "score_threshold": 0.5,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert [hit["id"] for hit in payload["hits"]] == ["hit-a"]
    assert payload["hits"][0]["document"] == "bon hit"


def test_search_omits_documents_when_not_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    api = reload_api(monkeypatch, token="search-token")

    class FakeCollection:
        def query(self, **_kwargs):
            return {
                "documents": [["contenu"]],
                "metadatas": [[{"source": "a.pdf"}]],
                "ids": [["hit-a"]],
                "distances": [[0.12]],
            }

    class FakeClient:
        def get_or_create_collection(self, *_args, **_kwargs):
            return FakeCollection()

    class FakeEmbeddings:
        def __init__(self, *_args, **_kwargs):
            pass

        def embed_query(self, _query):
            return [0.1, 0.2, 0.3]

    monkeypatch.setattr(api, "get_chroma_client", lambda: FakeClient())
    monkeypatch.setattr(api, "TimedOllamaEmbeddings", FakeEmbeddings)

    client = TestClient(api.app)
    response = client.post(
        "/search",
        headers={"X-API-Token": "search-token"},
        json={
            "q": "suites",
            "k": 5,
            "include_documents": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["hits"] == [
        {
            "id": "hit-a",
            "metadata": {"source": "a.pdf"},
            "score": 0.12,
        }
    ]


def test_search_maths_premiere_falls_back_to_education(monkeypatch: pytest.MonkeyPatch) -> None:
    api = reload_api(monkeypatch, token="search-token")

    class FakeCollection:
        def __init__(self, name: str) -> None:
            self.name = name

        def count(self) -> int:
            if self.name == "rag_maths_premiere":
                return 0
            return 10377

        def query(self, **kwargs):
            assert kwargs["where"] == {
                "$and": [
                    {"type_ressource": "Exercices"},
                    {"matiere": "Mathématiques"},
                    {"niveau": "Première"},
                    {"groupe": "Enseignements de spécialité (EDS)"},
                ]
            }
            return {
                "documents": [["suite"]],
                "metadatas": [[{"source": "suites.pdf"}]],
                "ids": [["hit-maths"]],
                "distances": [[0.11]],
            }

    class FakeClient:
        def __init__(self) -> None:
            self.requested_names: list[str] = []

        def get_or_create_collection(self, name: str, **_kwargs):
            self.requested_names.append(name)
            return FakeCollection(name)

    class FakeEmbeddings:
        def __init__(self, *_args, **_kwargs):
            pass

        def embed_query(self, _query):
            return [0.1, 0.2, 0.3]

    fake_client = FakeClient()
    monkeypatch.setattr(api, "get_chroma_client", lambda: fake_client)
    monkeypatch.setattr(api, "TimedOllamaEmbeddings", FakeEmbeddings)

    client = TestClient(api.app)
    response = client.post(
        "/search",
        headers={"X-API-Token": "search-token"},
        json={
            "q": "suites",
            "k": 5,
            "section": "maths_premiere",
            "filters": {"type_ressource": "Exercices"},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["collection"] == "rag_education"
    assert payload["maths_premiere_fallback"] is True
    assert payload["returned"] == 1
    assert fake_client.requested_names == ["rag_maths_premiere", "rag_education"]


def test_background_drive_ingest_loads_docx_files(monkeypatch: pytest.MonkeyPatch) -> None:
    api = reload_api(monkeypatch, token="drive-token")

    file_meta = {
        "id": "docx-1",
        "name": "cours.docx",
        "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "modifiedTime": "2026-04-19T07:00:00Z",
    }
    task = api.DriveTaskProgress(task_id="task-docx", folder_id="folder", target_collection="rag_maths_premiere")
    api._drive_tasks["task-docx"] = task

    monkeypatch.setattr(api.sync_manager, "verify_folder_access", lambda _folder_id: {"id": "folder"})
    monkeypatch.setattr(api.sync_manager, "list_updates", lambda _folder_id, collection_name=None: [file_meta])
    monkeypatch.setattr(api.sync_manager, "is_unchanged", lambda *args, **kwargs: False)
    monkeypatch.setattr(api.sync_manager, "mark_as_ingested", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        api,
        "_load_docx_documents_from_bytes",
        lambda content_bytes, source_name: [api.Document(page_content="DOCX texte", metadata={"source": source_name})],
    )
    monkeypatch.setattr(api, "_download_drive_file_bytes", lambda file_id: b"docx-bytes")
    monkeypatch.setattr(
        api,
        "_prepare_chunks_for_chroma",
        lambda req, docs, extra_metadata=None: api.PreparedBatch(
            ids=["h1"],
            documents=[docs[0].page_content],
            metadatas=[{"source": docs[0].metadata["source"]}],
            modality="text",
        ),
    )
    monkeypatch.setattr(api, "_index_batch", lambda *args, **kwargs: {"added": 1, "skipped": 0})

    api.background_drive_ingest("folder", {"collection": "rag_maths_premiere"}, "task-docx")

    assert task.status == "done"
    assert task.file_results[0]["status"] == "ok"
    assert task.added_chunks == 1


def test_background_drive_ingest_marks_xlsx_as_unsupported(monkeypatch: pytest.MonkeyPatch) -> None:
    api = reload_api(monkeypatch, token="drive-token")

    file_meta = {
        "id": "xlsx-1",
        "name": "planning.xlsx",
        "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "modifiedTime": "2026-04-19T07:00:00Z",
    }
    task = api.DriveTaskProgress(task_id="task-xlsx", folder_id="folder", target_collection="rag_maths_premiere")
    api._drive_tasks["task-xlsx"] = task

    monkeypatch.setattr(api.sync_manager, "verify_folder_access", lambda _folder_id: {"id": "folder"})
    monkeypatch.setattr(api.sync_manager, "list_updates", lambda _folder_id, collection_name=None: [file_meta])

    api.background_drive_ingest("folder", {"collection": "rag_maths_premiere"}, "task-xlsx")

    assert task.status == "done"
    assert task.file_results[0]["status"] == "unsupported"
    assert "spreadsheet" in task.file_results[0]["detail"].lower()


def test_upload_media_requires_explicit_multimodal_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    api = reload_api(monkeypatch, token="upload-token")

    class FakeCollection:
        def get(self, **_kwargs):
            return {"ids": []}

    class FakeClient:
        def get_or_create_collection(self, *_args, **_kwargs):
            return FakeCollection()

    def fail_if_multimodal_called(*_args, **_kwargs):
        raise AssertionError("parse_multimodal must not be called for mode=text uploads")

    monkeypatch.setattr(api, "get_chroma_client", lambda: FakeClient())
    monkeypatch.setattr(api, "parse_multimodal", fail_if_multimodal_called)
    monkeypatch.setenv("ADMIN_UPLOAD_DIR", str(tmp_path))

    client = TestClient(api.app)
    response = client.post(
        "/ingest/upload-files?mode=text",
        headers={"X-API-Token": "upload-token"},
        files={"files": ("cours.webm", b"fake-webm-content", "video/webm")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_errors"] == 1
    assert body["results"][0]["status"] == "error"
    assert "multimodal" in body["results"][0]["detail"].lower()
