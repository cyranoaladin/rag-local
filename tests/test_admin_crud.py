from __future__ import annotations

from importlib import import_module

import pytest

from tests.test_admin_router_basic import _load_app


def test_admin_crud_and_oneclick(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    client, api_key = _load_app(monkeypatch, tmp_path)
    headers = {"X-API-Key": api_key, "Origin": "https://ops.example.com"}

    tenant_resp = client.post("/admin/tenants", json={"slug": "beta"}, headers=headers)
    assert tenant_resp.status_code == 200
    assert tenant_resp.json()["tenant"] == "beta"

    taxonomy_resp = client.post(
        "/admin/taxonomy",
        json={"tenant": "edu", "facet": "doc_type", "value": "cours"},
        headers=headers,
    )
    assert taxonomy_resp.status_code == 200
    assert taxonomy_resp.json()["value"] == "cours"

    key_resp = client.post(
        "/admin/api-keys",
        json={
            "tenant": "web3",
            "scopes": ["kb:read"],
            "origins": ["https://ops.example.com"],
        },
        headers=headers,
    )
    assert key_resp.status_code == 200
    assert key_resp.json()["tenant"] == "web3"
    assert key_resp.json()["key"].startswith("rag_")

    ingest_resp = client.post(
        "/admin/ingest/oneclick",
        json={
            "tenant": "edu",
            "folder_path": "guides/analysis",
            "source_type": "url",
            "source_value": "https://example.org/analysis",
            "taxonomy": {"doc_type": "cours"},
            "mode": "text",
        },
        headers=headers,
    )
    assert ingest_resp.status_code == 202
    payload = ingest_resp.json()
    assert payload["tenant"] == "edu"
    assert payload["status"] == "done"
    assert payload["metadata"]["doc_type"] == "cours"

    router_module = import_module("src.admin.router")
    service = router_module._SERVICE  # type: ignore[attr-defined]
    job = service.get_job(payload["jobId"])
    assert job is not None
    events = service.list_job_events(job.id)
    assert any("completed" in event.message for event in events)
