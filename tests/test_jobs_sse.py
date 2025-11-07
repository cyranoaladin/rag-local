from __future__ import annotations

from importlib import import_module

import pytest

from tests.test_admin_router_basic import _load_app


def test_sse_streams_existing_events(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    client, api_key = _load_app(monkeypatch, tmp_path)
    router_module = import_module("src.admin.router")
    service = router_module._SERVICE  # type: ignore[attr-defined]

    folder = service.ensure_folder("edu", "jobs/sse")
    collection = service.ensure_collection("edu", "edu__jobs-sse", folder=folder)
    job = service.create_job(
        job_id="job-sse-1",
        tenant_slug="edu",
        folder_id=folder.id,
        collection_name=collection.name,
        source_type="url",
        source_value="https://example.org",
        status="queued",
    )
    service.append_job_event(job.id, "info", "Job queued for ingestion")

    headers = {"X-API-Key": api_key, "Origin": "https://ops.example.com"}
    with client.stream("GET", f"/admin/jobs/{job.id}/events", headers=headers) as response:
        assert response.status_code == 200
        iterator = response.iter_lines()
        first_lines = [next(iterator) for _ in range(3)]
        assert first_lines[1] == "event: message"
        assert "Job queued" in first_lines[2]


def test_sse_rejects_unknown_job(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    client, api_key = _load_app(monkeypatch, tmp_path)
    headers = {"X-API-Key": api_key, "Origin": "https://ops.example.com"}
    response = client.get("/admin/jobs/does-not-exist/events", headers=headers)
    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found for tenant"
