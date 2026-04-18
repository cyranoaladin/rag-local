from __future__ import annotations

import math
from collections.abc import Generator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.ingestor.api import app as ingest_app
from tests.integration.mocks.embedding_utils import generate_fake_embedding


@pytest.fixture
def fake_chroma_store() -> dict[str, StoredVector]:
    return {}


def pytest_collection_modifyitems(items):
    """Automatically mark all tests in this directory as integration tests."""
    for item in items:
        # Only mark if the test file is inside tests/integration
        if "tests/integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)


@dataclass
class StoredVector:
    vector_id: str
    document: str
    metadata: dict[str, Any]
    embedding: list[float]


class FakeChromaCollection:
    def __init__(self, store: dict[str, StoredVector]):
        self._store = store

    def get(self, ids: Sequence[str] | None = None) -> dict[str, Any]:
        if not ids:
            return {"ids": [], "documents": [], "metadatas": []}
        found = [item_id for item_id in ids if item_id in self._store]
        documents = [self._store[item_id].document for item_id in found]
        metadatas = [self._store[item_id].metadata for item_id in found]
        return {"ids": found, "documents": documents, "metadatas": metadatas}

    def add(
        self,
        documents: Sequence[str],
        ids: Sequence[str],
        metadatas: Sequence[Mapping[str, Any]],
        embeddings: Sequence[Sequence[float]],
    ) -> None:
        count = min(len(documents), len(ids), len(metadatas), len(embeddings))
        for index in range(count):
            vector_id = ids[index]
            document = documents[index]
            metadata = dict(metadatas[index])
            embedding = [float(value) for value in embeddings[index]]
            self._store[vector_id] = StoredVector(
                vector_id=vector_id,
                document=document,
                metadata=metadata,
                embedding=embedding,
            )

    def query(self, query_texts: Sequence[str], n_results: int) -> dict[str, Any]:
        ids: list[list[str]] = []
        documents: list[list[str]] = []
        metadatas: list[list[dict[str, Any]]] = []
        distances: list[list[float]] = []
        for query_text in query_texts:
            query_embedding = generate_fake_embedding(query_text)
            scored: list[tuple[float, StoredVector]] = []
            for item in self._store.values():
                score = _cosine_distance(query_embedding, item.embedding)
                scored.append((score, item))
            scored.sort(key=lambda pair: pair[0])
            top = scored[: max(0, n_results)]
            ids.append([item.vector_id for _, item in top])
            documents.append([item.document for _, item in top])
            metadatas.append([item.metadata for _, item in top])
            distances.append([score for score, _ in top])
        return {
            "ids": ids,
            "documents": documents,
            "metadatas": metadatas,
            "distances": distances,
        }


class FakeChromaClient:
    def __init__(self, collection: FakeChromaCollection):
        self._collection = collection

    def get_or_create_collection(self, name: str, metadata: Mapping[str, Any] | None = None) -> FakeChromaCollection:  # noqa: ARG002
        return self._collection


class DummyTimedEmbeddings:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.model = kwargs.get("model")

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [generate_fake_embedding(text) for text in texts]


def _cosine_distance(vector_a: Sequence[float], vector_b: Sequence[float]) -> float:
    if not vector_a or not vector_b:
        return 1.0
    # Python 3.9 compatibility: zip(strict=...) not available
    numerator = sum(x * y for x, y in zip(vector_a, vector_b, strict=False))
    denominator = math.sqrt(sum(x * x for x in vector_a)) * math.sqrt(sum(y * y for y in vector_b))
    if denominator == 0:
        return 1.0
    similarity = max(-1.0, min(1.0, numerator / denominator))
    return round(1.0 - similarity, 6)


@pytest.fixture
def fake_chroma_collection(fake_chroma_store: dict[str, StoredVector]) -> FakeChromaCollection:
    return FakeChromaCollection(fake_chroma_store)


@pytest.fixture(autouse=True)
def _patch_chroma_client(mocker, fake_chroma_collection: FakeChromaCollection):
    mocker.patch("src.ingestor.api.get_chroma_client", return_value=FakeChromaClient(fake_chroma_collection))
    return fake_chroma_collection


@pytest.fixture(autouse=True)
def _patch_ollama_embeddings(mocker):
    mocker.patch("src.ingestor.api.TimedOllamaEmbeddings", DummyTimedEmbeddings)


@pytest.fixture(autouse=True)
def _ingestor_env(monkeypatch):
    base_dir = Path(__file__).resolve().parent
    monkeypatch.setenv("LOCAL_SOURCE_ROOT", str(base_dir))
    monkeypatch.setenv("INGESTOR_API_TOKEN", "test-token")
    monkeypatch.setenv("CHROMA_REQUEST_TIMEOUT", "5")
    monkeypatch.setenv("OLLAMA_REQUEST_TIMEOUT", "5")
    monkeypatch.delenv("INGESTOR_IP_ALLOWLIST", raising=False)


@pytest.fixture
def ingestor_client() -> Generator[TestClient, None, None]:
    with TestClient(ingest_app) as client:
        yield client


@pytest.fixture
def seeded_chroma(fake_chroma_collection: FakeChromaCollection) -> FakeChromaCollection:
    documents = [
        ("seed-1", "Programmation fonctionnelle en Python", {"source": "seed://functional"}),
        ("seed-2", "Structures de données et algorithmes", {"source": "seed://algorithms"}),
    ]
    for vector_id, text, metadata in documents:
        fake_chroma_collection.add(
            documents=[text],
            ids=[vector_id],
            metadatas=[metadata],
            embeddings=[generate_fake_embedding(text)],
        )
    return fake_chroma_collection
