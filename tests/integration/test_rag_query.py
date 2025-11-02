from __future__ import annotations

from typing import Any

from langchain_core.documents import Document

INGEST_ENDPOINT = "/ingest"
DEFAULT_PAYLOAD: dict[str, Any] = {
    "source": "https://example.org/course",
    "source_type": "url",
    "hints": {"matiere": "NSI"},
}


def _first_document(result: dict[str, Any]) -> str:
    documents = result.get("documents") or []
    if not documents or not documents[0]:
        return ""
    return documents[0][0]


def _headers(token: str = "test-token") -> dict[str, str]:
    return {"Content-Type": "application/json", "X-API-Token": token}


def test_query_returns_seeded_documents(seeded_chroma) -> None:
    result = seeded_chroma.query(query_texts=["Programmation fonctionnelle"], n_results=2)
    first_doc = _first_document(result)
    assert "Programmation fonctionnelle" in first_doc


def test_query_highlights_recently_ingested_documents(
    ingestor_client,
    seeded_chroma,
    mocker,
) -> None:
    new_text = "Introduction aux automates finis"
    mocker.patch("src.ingestor.api._load_source_documents", return_value=[Document(page_content=new_text, metadata={"source": "unit-test"})])

    response = ingestor_client.post(
        INGEST_ENDPOINT,
        json=DEFAULT_PAYLOAD,
        headers=_headers(),
    )
    assert response.status_code == 200

    result = seeded_chroma.query(query_texts=[new_text], n_results=1)
    assert _first_document(result) == new_text
