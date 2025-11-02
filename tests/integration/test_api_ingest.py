from __future__ import annotations

from typing import Any

from langchain_core.documents import Document

INGEST_ENDPOINT = "/ingest"
DEFAULT_PAYLOAD: dict[str, Any] = {
    "source": "https://example.org/course",
    "source_type": "url",
    "hints": {"matiere": "NSI", "niveau": "Terminale"},
}


def _with_headers(token: str | None = None, forwarded_for: str | None = None) -> dict[str, str]:
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if token is not None:
        headers["X-API-Token"] = token
    if forwarded_for is not None:
        headers["X-Forwarded-For"] = forwarded_for
    return headers


def _document(text: str) -> list[Document]:
    return [Document(page_content=text, metadata={"source": "unit-test"})]


def test_ingest_rejects_missing_token(ingestor_client) -> None:
    response = ingestor_client.post(INGEST_ENDPOINT, json=DEFAULT_PAYLOAD)
    assert response.status_code == 401


def test_ingest_rejects_invalid_token(ingestor_client) -> None:
    response = ingestor_client.post(
        INGEST_ENDPOINT,
        json=DEFAULT_PAYLOAD,
        headers=_with_headers(token="bad-token"),
    )
    assert response.status_code == 401


def test_ingest_accepts_valid_token(ingestor_client, fake_chroma_store, mocker) -> None:
    mocker.patch(
        "src.ingestor.api._load_source_documents",
        return_value=_document("Introduction aux arbres binaires"),
    )
    response = ingestor_client.post(
        INGEST_ENDPOINT,
        json=DEFAULT_PAYLOAD,
        headers=_with_headers(token="test-token"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body.get("status") == "ok"
    assert sum(1 for item in fake_chroma_store.values() if "arbres" in item.document.lower()) == 1


def test_ingest_rejects_ip_not_allowlisted(monkeypatch, ingestor_client, mocker) -> None:
    monkeypatch.setenv("INGESTOR_IP_ALLOWLIST", "1.1.1.1")
    mocker.patch(
        "src.ingestor.api._load_source_documents",
        return_value=_document("Programmation fonctionnelle"),
    )

    response = ingestor_client.post(
        INGEST_ENDPOINT,
        json=DEFAULT_PAYLOAD,
        headers=_with_headers(token="test-token", forwarded_for="2.2.2.2"),
    )

    assert response.status_code == 403
    detail = response.json().get("detail")
    assert "Forbidden" in detail


def test_ingest_allows_request_from_allowlisted_ip(monkeypatch, ingestor_client, fake_chroma_store, mocker) -> None:
    monkeypatch.setenv("INGESTOR_IP_ALLOWLIST", "1.1.1.0/30")
    mocker.patch(
        "src.ingestor.api._load_source_documents",
        return_value=_document("Cours de graphes avancés"),
    )

    response = ingestor_client.post(
        INGEST_ENDPOINT,
        json=DEFAULT_PAYLOAD,
        headers=_with_headers(token="test-token", forwarded_for="1.1.1.1"),
    )

    assert response.status_code == 200
    assert any("graphes" in item.document.lower() for item in fake_chroma_store.values())