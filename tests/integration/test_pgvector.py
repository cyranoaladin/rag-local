"""
Tests d'intégration pgvector.
Requiert une base pgvector disponible (utilise DATABASE_URL_TEST).

Usage :
    DATABASE_URL_TEST="postgresql://raguser:test@localhost:5435/ragdb_test" \
    pytest tests/test_integration_pgvector.py -v
"""
from __future__ import annotations

import os

import pytest

from ingestor.database import RagDatabase

DSN = os.getenv(
    "DATABASE_URL_TEST",
    "postgresql://raguser:test@localhost:5435/ragdb_test",
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("DATABASE_URL_TEST"),
        reason="DATABASE_URL_TEST not set — skip integration tests",
    ),
]


@pytest.fixture
async def db():
    """Fixture : connexion à la base de test."""
    database = RagDatabase(DSN)
    await database.connect(min_size=1, max_size=3)
    yield database
    await database.disconnect()


@pytest.mark.asyncio
async def test_upsert_and_retrieve_document(db: RagDatabase) -> None:
    """Test upsert d'un document et récupération."""
    doc_id = await db.upsert_document(
        tenant="test",
        source_type="markdown",
        source_path="/test/doc_integration.md",
        title="Document de test intégration",
        file_hash="abc123integration",
        embed_model="nomic-embed-text:v1.5",
        embed_dim=768,
    )
    assert doc_id is not None
    assert len(doc_id) == 36  # UUID format

    docs = await db.list_documents("test")
    found = [d for d in docs if str(d["id"]) == doc_id]
    assert len(found) == 1
    assert found[0]["title"] == "Document de test intégration"

    # Cleanup
    await db.delete_document(doc_id, "test")


@pytest.mark.asyncio
async def test_upsert_idempotent(db: RagDatabase) -> None:
    """Test que l'upsert est idempotent (même source_path + tenant)."""
    doc_id_1 = await db.upsert_document(
        tenant="test",
        source_type="markdown",
        source_path="/test/idempotent.md",
        title="Version 1",
        file_hash="hash1",
        embed_model="nomic-embed-text:v1.5",
        embed_dim=768,
    )
    doc_id_2 = await db.upsert_document(
        tenant="test",
        source_type="markdown",
        source_path="/test/idempotent.md",
        title="Version 2",
        file_hash="hash2",
        embed_model="nomic-embed-text:v1.5",
        embed_dim=768,
    )
    assert doc_id_1 == doc_id_2

    docs = await db.list_documents("test")
    found = [d for d in docs if str(d["id"]) == doc_id_1]
    assert len(found) == 1
    assert found[0]["title"] == "Version 2"

    # Cleanup
    await db.delete_document(doc_id_1, "test")


@pytest.mark.asyncio
async def test_insert_and_search_chunks(db: RagDatabase) -> None:
    """Test insertion de chunks et recherche dense."""
    doc_id = await db.upsert_document(
        tenant="test",
        source_type="markdown",
        source_path="/test/search_integration.md",
        title="Test recherche intégration",
        file_hash="searchhash",
        embed_model="test-model",
        embed_dim=4,
    )

    # Insérer des chunks avec embeddings factices (dim=4 pour le test)
    inserted = await db.insert_chunks(doc_id, "test", [
        {
            "chunk_index": 0,
            "text": "Python est un langage de programmation",
            "embedding": [0.1, 0.2, 0.3, 0.4],
        },
        {
            "chunk_index": 1,
            "text": "JavaScript est utilisé pour le web",
            "embedding": [0.9, 0.1, 0.0, 0.1],
        },
    ])
    assert inserted == 2

    # Recherche dense
    results = await db.dense_search([0.1, 0.2, 0.3, 0.4], "test", k=5)
    assert len(results) > 0
    assert results[0]["text"] == "Python est un langage de programmation"

    # Cleanup
    await db.delete_document(doc_id, "test")


@pytest.mark.asyncio
async def test_sparse_search(db: RagDatabase) -> None:
    """Test recherche BM25 (sparse)."""
    doc_id = await db.upsert_document(
        tenant="test",
        source_type="markdown",
        source_path="/test/sparse_integration.md",
        title="Test sparse",
        file_hash="sparsehash",
        embed_model="test-model",
        embed_dim=4,
    )

    await db.insert_chunks(doc_id, "test", [
        {
            "chunk_index": 0,
            "text": "La complexité algorithmique mesure l'efficacité d'un algorithme",
            "embedding": [0.1, 0.2, 0.3, 0.4],
        },
        {
            "chunk_index": 1,
            "text": "Le réseau TCP/IP est la base d'Internet",
            "embedding": [0.5, 0.6, 0.7, 0.8],
        },
    ])

    # Recherche BM25
    results = await db.sparse_search("complexité algorithmique", "test", k=5)
    assert len(results) > 0
    assert "complexité" in results[0]["text"].lower()

    # Cleanup
    await db.delete_document(doc_id, "test")


@pytest.mark.asyncio
async def test_get_stats(db: RagDatabase) -> None:
    """Test statistiques par tenant."""
    doc_id = await db.upsert_document(
        tenant="test_stats",
        source_type="pdf",
        source_path="/test/stats.pdf",
        title="Stats doc",
        file_hash="statshash",
        embed_model="nomic-embed-text:v1.5",
        embed_dim=768,
    )

    stats = await db.get_stats("test_stats")
    assert stats["doc_count"] >= 1

    # Cleanup
    await db.delete_document(doc_id, "test_stats")


@pytest.mark.asyncio
async def test_list_tenants(db: RagDatabase) -> None:
    """Test liste des tenants."""
    doc_id = await db.upsert_document(
        tenant="test_tenant_list",
        source_type="markdown",
        source_path="/test/tenant_list.md",
        title="Tenant test",
        file_hash="tenanthash",
        embed_model="test-model",
        embed_dim=768,
    )

    tenants = await db.list_tenants()
    assert "test_tenant_list" in tenants

    # Cleanup
    await db.delete_document(doc_id, "test_tenant_list")


@pytest.mark.asyncio
async def test_delete_cascades_chunks(db: RagDatabase) -> None:
    """Test que la suppression d'un document supprime ses chunks (CASCADE)."""
    doc_id = await db.upsert_document(
        tenant="test",
        source_type="markdown",
        source_path="/test/cascade_delete.md",
        title="Cascade delete test",
        file_hash="cascadehash",
        embed_model="test-model",
        embed_dim=4,
    )

    await db.insert_chunks(doc_id, "test", [
        {"chunk_index": 0, "text": "Chunk à supprimer", "embedding": [0.1, 0.2, 0.3, 0.4]},
    ])

    deleted = await db.delete_document(doc_id, "test")
    assert deleted is True

    # Vérifier que les chunks sont aussi supprimés
    results = await db.dense_search([0.1, 0.2, 0.3, 0.4], "test", k=10)
    chunk_ids = [str(r["document_id"]) for r in results]
    assert doc_id not in chunk_ids
