"""
Couche d'accès pgvector — remplace ChromaDB intégralement.
Toutes les opérations vectorielles passent par ce module.
"""
from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

try:
    import asyncpg
except ImportError:
    asyncpg = None

logger = logging.getLogger(__name__)


class RagDatabase:
    """Client pgvector async haute performance."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self._pool: asyncpg.Pool | None = None

    async def connect(self, min_size: int = 5, max_size: int = 20) -> None:
        """Initialise le pool de connexions."""
        self._pool = await asyncpg.create_pool(
            self.dsn,
            min_size=min_size,
            max_size=max_size,
            command_timeout=60,
            init=self._init_connection,
        )
        logger.info("pgvector pool connected (min=%d, max=%d)", min_size, max_size)

    async def _init_connection(self, conn: asyncpg.Connection) -> None:
        """Configure chaque connexion du pool."""
        await conn.execute("SET search_path TO public")
        await conn.execute("SET hnsw.ef_search = 100")

    async def disconnect(self) -> None:
        """Ferme le pool de connexions."""
        if self._pool:
            await self._pool.close()
            logger.info("pgvector pool disconnected")

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[asyncpg.Connection]:
        """Acquiert une connexion du pool."""
        if self._pool is None:
            raise RuntimeError("Database pool not initialized. Call connect() first.")
        async with self._pool.acquire() as conn:
            yield conn

    # ─── INGESTION ───────────────────────────────────────────────

    async def upsert_document(
        self,
        tenant: str,
        source_type: str,
        source_path: str,
        title: str,
        file_hash: str,
        embed_model: str,
        embed_dim: int,
        label: str | None = None,
        mime_type: str | None = None,
        char_count: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Insert ou update un document, retourne son UUID."""
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO rag_documents
                    (tenant, source_type, source_path, title, file_hash,
                     embed_model, embed_dim, label, mime_type, char_count, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb)
                ON CONFLICT (source_path, tenant) DO UPDATE SET
                    title = EXCLUDED.title,
                    file_hash = EXCLUDED.file_hash,
                    embed_model = EXCLUDED.embed_model,
                    embed_dim = EXCLUDED.embed_dim,
                    label = EXCLUDED.label,
                    mime_type = EXCLUDED.mime_type,
                    char_count = EXCLUDED.char_count,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW()
                RETURNING id
                """,
                tenant,
                source_type,
                source_path,
                title,
                file_hash,
                embed_model,
                embed_dim,
                label,
                mime_type,
                char_count,
                json.dumps(metadata or {}),
            )
            return str(row["id"])

    async def insert_chunks(
        self,
        document_id: str,
        tenant: str,
        chunks: list[dict[str, Any]],
    ) -> int:
        """Insert les chunks avec leurs embeddings en batch.

        Args:
            document_id: UUID du document parent.
            tenant: Identifiant du tenant.
            chunks: Liste de dicts avec keys: text, embedding, chunk_index,
                    et optionnellement char_start, char_end, page_number, metadata.

        Returns:
            Nombre de chunks insérés.
        """
        doc_uuid = uuid.UUID(document_id)
        async with self.acquire() as conn:
            # Supprimer les anciens chunks de ce document
            await conn.execute(
                "DELETE FROM rag_chunks WHERE document_id = $1",
                doc_uuid,
            )
            # Insert batch
            records = []
            for c in chunks:
                emb = c["embedding"]
                emb_str = f"[{','.join(map(str, emb))}]"
                records.append(
                    (
                        doc_uuid,
                        tenant,
                        c["chunk_index"],
                        c["text"],
                        emb_str,
                        c.get("char_start"),
                        c.get("char_end"),
                        c.get("page_number"),
                        json.dumps(c.get("metadata", {})),
                    )
                )
            await conn.executemany(
                """
                INSERT INTO rag_chunks
                    (document_id, tenant, chunk_index, text, embedding,
                     char_start, char_end, page_number, metadata)
                VALUES ($1, $2, $3, $4, $5::vector, $6, $7, $8, $9::jsonb)
                """,
                records,
            )
            return len(records)

    # ─── RECHERCHE ───────────────────────────────────────────────

    async def dense_search(
        self,
        embedding: list[float],
        tenant: str,
        k: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Recherche par similarité cosine (dense vector search)."""
        embedding_str = f"[{','.join(map(str, embedding))}]"

        where_clauses = ["c.tenant = $2"]
        params: list[Any] = [embedding_str, tenant]
        param_idx = 3

        if filters:
            if filters.get("document_id"):
                where_clauses.append(f"c.document_id = ${param_idx}::uuid")
                params.append(filters["document_id"])
                param_idx += 1
            if filters.get("source_type"):
                where_clauses.append(f"d.source_type = ${param_idx}")
                params.append(filters["source_type"])
                param_idx += 1
            # Metadata JSONB filters for taxonomy (section, matiere, niveau, groupe)
            for meta_key in ("section", "matiere", "niveau", "groupe"):
                if filters.get(meta_key):
                    where_clauses.append(f"c.metadata->>'{meta_key}' = ${param_idx}")
                    params.append(filters[meta_key])
                    param_idx += 1

        where_sql = " AND ".join(where_clauses)

        async with self.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT
                    c.id, c.document_id, c.chunk_index, c.text,
                    c.page_number, c.metadata,
                    d.title, d.source_path, d.source_type,
                    1 - (c.embedding <=> $1::vector) AS score
                FROM rag_chunks c
                JOIN rag_documents d ON d.id = c.document_id
                WHERE {where_sql}
                ORDER BY c.embedding <=> $1::vector
                LIMIT {k}
                """,
                *params,
            )
            return [dict(r) for r in rows]

    async def sparse_search(
        self,
        query: str,
        tenant: str,
        k: int = 20,
    ) -> list[dict[str, Any]]:
        """Recherche BM25 via full-text PostgreSQL."""
        async with self.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    c.id, c.document_id, c.chunk_index, c.text,
                    c.page_number, c.metadata,
                    d.title, d.source_path, d.source_type,
                    ts_rank_cd(c.text_tsv, query) AS score
                FROM rag_chunks c
                JOIN rag_documents d ON d.id = c.document_id,
                plainto_tsquery('french', $1) query
                WHERE c.tenant = $2
                  AND c.text_tsv @@ query
                ORDER BY score DESC
                LIMIT $3
                """,
                query,
                tenant,
                k,
            )
            return [dict(r) for r in rows]

    # ─── ADMIN ───────────────────────────────────────────────────

    async def list_documents(
        self, tenant: str, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Liste les documents d'un tenant."""
        async with self.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, source_type, source_path, title, label, chunk_count,
                       embed_model, embed_dim, ingested_at, updated_at, metadata
                FROM rag_documents
                WHERE tenant = $1
                ORDER BY ingested_at DESC
                LIMIT $2 OFFSET $3
                """,
                tenant,
                limit,
                offset,
            )
            return [dict(r) for r in rows]

    async def delete_document(self, document_id: str, tenant: str) -> bool:
        """Supprime un document et ses chunks (CASCADE)."""
        doc_uuid = uuid.UUID(document_id)
        async with self.acquire() as conn:
            result = cast(str, await conn.execute(
                "DELETE FROM rag_documents WHERE id = $1 AND tenant = $2",
                doc_uuid,
                tenant,
            ))
            return result == "DELETE 1"

    async def get_stats(self, tenant: str) -> dict[str, Any]:
        """Statistiques agrégées pour un tenant."""
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    COUNT(DISTINCT d.id) AS doc_count,
                    COALESCE(SUM(d.chunk_count), 0) AS chunk_count,
                    COUNT(DISTINCT d.embed_model) AS embed_model_count,
                    MAX(d.embed_model) AS embed_model,
                    MAX(d.updated_at) AS last_updated
                FROM rag_documents d
                WHERE d.tenant = $1
                """,
                tenant,
            )
            return dict(row) if row else {}

    async def list_tenants(self) -> list[str]:
        """Liste tous les tenants distincts."""
        async with self.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT tenant FROM rag_documents ORDER BY tenant"
            )
            return [r["tenant"] for r in rows]

    async def document_exists(self, source_path: str, tenant: str) -> str | None:
        """Vérifie si un document existe déjà par source_path, retourne son ID ou None."""
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM rag_documents WHERE source_path = $1 AND tenant = $2",
                source_path,
                tenant,
            )
            return str(row["id"]) if row else None

    async def document_exists_by_hash(self, file_hash: str, tenant: str) -> str | None:
        """Vérifie si un document existe déjà par file_hash, retourne son ID ou None."""
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM rag_documents WHERE file_hash = $1 AND tenant = $2",
                file_hash,
                tenant,
            )
            return str(row["id"]) if row else None

    async def check_duplicates(
        self, sources: list[str], tenant: str
    ) -> list[dict[str, Any]]:
        """Vérifie en batch si des documents existent déjà (par source_path ou file_hash)."""
        results: list[dict[str, Any]] = []
        async with self.acquire() as conn:
            for source in sources:
                row = await conn.fetchrow(
                    """
                    SELECT id, source_path, file_hash
                    FROM rag_documents
                    WHERE (source_path = $1 OR file_hash = $1) AND tenant = $2
                    """,
                    source,
                    tenant,
                )
                results.append({
                    "source": source,
                    "already_ingested": row is not None,
                    "document_id": str(row["id"]) if row else None,
                })
        return results

    # ─── ÉVALUATION ──────────────────────────────────────────────

    async def save_eval_run(
        self,
        tenant: str,
        embed_model: str,
        precision_at_5: float,
        recall_at_5: float,
        mrr: float,
        ndcg: float | None = None,
        avg_latency_ms: float | None = None,
        gold_set_version: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Sauvegarde les résultats d'une évaluation RAG."""
        async with self.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO rag_eval_runs
                    (tenant, embed_model, precision_at_5, recall_at_5, mrr,
                     ndcg, avg_latency_ms, gold_set_version, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
                RETURNING id
                """,
                tenant,
                embed_model,
                precision_at_5,
                recall_at_5,
                mrr,
                ndcg,
                avg_latency_ms,
                gold_set_version,
                json.dumps(metadata or {}),
            )
            return str(row["id"])

    async def list_eval_runs(
        self, tenant: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Historique des évaluations pour un tenant."""
        async with self.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, tenant, run_at, embed_model,
                       precision_at_5, recall_at_5, mrr, ndcg,
                       avg_latency_ms, gold_set_version, metadata
                FROM rag_eval_runs
                WHERE tenant = $1
                ORDER BY run_at DESC
                LIMIT $2
                """,
                tenant,
                limit,
            )
            return [dict(r) for r in rows]
