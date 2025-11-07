from __future__ import annotations

import json
import sys
from importlib import import_module
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

MODULES_TO_RESET = [
    "src.ingestor.api",
    "src.ingestor.search_api",
    "src.admin.router",
    "src.admin.service",
    "src.admin.models",
    "src.common.auth",
    "src.common.ratelimit",
]


def _prepare_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, rate_limit: str = "10") -> str:
    api_key = "demo_ops"
    keys_path = tmp_path / "api_keys.json"
    keys_payload = {
        api_key: {
            "tenant": "edu",
            "scopes": [
                "folders:read",
                "folders:write",
                "ingest:write",
                "jobs:read",
                "kb:read",
                "keys:issue",
            ],
            "origins": ["https://ops.example.com"],
            "note": "test key",
        }
    }
    keys_path.write_text(json.dumps(keys_payload), encoding="utf-8")
    db_path = tmp_path / "admin.db"
    monkeypatch.setenv("API_KEYS_PATH", str(keys_path))
    monkeypatch.setenv("ADMIN_DB_PATH", str(db_path))
    monkeypatch.setenv("RATE_LIMIT_RPM", rate_limit)
    monkeypatch.setenv("TENANTS", "edu,web3")
    monkeypatch.setenv("DEFAULT_TENANT", "edu")
    monkeypatch.setenv("RERANKER_ENABLED", "false")
    return api_key


def _load_app(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    rate_limit: str = "10",
) -> tuple[TestClient, str]:
    api_key = _prepare_env(monkeypatch, tmp_path, rate_limit=rate_limit)
    for module_name in MODULES_TO_RESET:
        sys.modules.pop(module_name, None)
    app_module = import_module("src.ingestor.api")
    client = TestClient(app_module.app)
    return client, api_key


def test_create_and_list_folders(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client, api_key = _load_app(monkeypatch, tmp_path)
    headers = {"X-API-Key": api_key, "Origin": "https://ops.example.com"}

    response = client.post(
        "/admin/folders",
        json={"tenant": "edu", "path": "guides/maths"},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["tenant"] == "edu"
    assert payload["folder"]["path"] == "guides/maths"
    assert payload["collection"].startswith("edu__")

    parent_id = payload["folder"]["parentId"]
    list_response = client.get(
        "/admin/folders",
        params={"tenant": "edu", "parent_id": parent_id},
        headers=headers,
    )
    assert list_response.status_code == 200
    folders = list_response.json()["folders"]
    assert any(entry["path"] == "guides/maths" for entry in folders)


def test_origin_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client, api_key = _load_app(monkeypatch, tmp_path)
    headers = {"X-API-Key": api_key, "Origin": "https://unauthorized.example"}
    response = client.get("/admin/folders", headers=headers)
    assert response.status_code == 403


def test_rate_limit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client, api_key = _load_app(monkeypatch, tmp_path, rate_limit="1")
    headers = {"X-API-Key": api_key, "Origin": "https://ops.example.com"}
    ok_response = client.get("/admin/folders", headers=headers)
    assert ok_response.status_code == 200
    limited_response = client.get("/admin/folders", headers=headers)
    assert limited_response.status_code == 429


def test_kb_search_with_folder_filters(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client, api_key = _load_app(monkeypatch, tmp_path)
    headers = {"X-API-Key": api_key, "Origin": "https://ops.example.com"}

    create_resp = client.post(
        "/admin/folders",
        json={"tenant": "edu", "path": "guides/blockchain"},
        headers=headers,
    )
    assert create_resp.status_code == 200

    from src.ingestor import search_api

    class DummyCollection:
        def query(self, query_texts, n_results):  # noqa: D401 - FastAPI test stub
            return {
                "documents": [["doc body"]],
                "metadatas": [[{"source": "dummy"}]],
                "ids": [["chunk-1"]],
                "distances": [[0.12]],
            }

    monkeypatch.setattr(search_api, "_collection", lambda name: DummyCollection())

    search_resp = client.post(
        "/kb/search",
        json={"q": "hello", "filters": {"folder_path": "guides/blockchain"}},
        headers=headers,
    )
    assert search_resp.status_code == 200
    body = search_resp.json()
    assert body["tenant"] == "edu"
    assert body["hits"]
    assert body["hits"][0]["metadata"]["source"] == "dummy"
