"""
Script de migration Qdrant → pgvector.
Lit les embeddings depuis Qdrant et les réinsère dans pgvector
SANS les recalculer (préserve la cohérence vectorielle).

Usage :
    python migrate_qdrant_to_pgvector.py \
        --qdrant-url http://localhost:6333 \
        --collection programmes_vf \
        --pg-dsn "postgresql://raguser:pass@localhost:5435/ragdb" \
        --tenant nexus
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import uuid
from typing import Any

import asyncpg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def migrate(
    qdrant_url: str,
    collection: str,
    pg_dsn: str,
    tenant: str,
    embed_model: str,
    embed_dim: int,
    batch_size: int = 100,
) -> None:
    """Migre une collection Qdrant vers pgvector.

    Args:
        qdrant_url: URL du serveur Qdrant.
        collection: Nom de la collection Qdrant.
        pg_dsn: DSN PostgreSQL.
        tenant: Identifiant du tenant cible.
        embed_model: Nom du modèle d'embedding utilisé.
        embed_dim: Dimension des vecteurs.
        batch_size: Taille des batchs de lecture Qdrant.
    """
    from qdrant_client import QdrantClient

    # Connexion Qdrant
    qdrant = QdrantClient(url=qdrant_url)

    try:
        coll_info = qdrant.get_collection(collection)
        total_points = coll_info.points_count or 0
        logger.info("Collection Qdrant '%s' : %d points", collection, total_points)
    except Exception as exc:
        logger.error("Impossible d'accéder à la collection '%s': %s", collection, exc)
        return

    if total_points == 0:
        logger.info("Collection vide, rien à migrer.")
        return

    # Connexion pgvector
    pool = await asyncpg.create_pool(pg_dsn, min_size=2, max_size=10)

    total_migrated = 0
    offset = None

    # Regrouper par doc_id pour créer des documents
    source_groups: dict[str, list[dict[str, Any]]] = {}

    logger.info("Lecture des points Qdrant...")

    while True:
        # Scroll à travers tous les points
        points, next_offset = qdrant.scroll(
            collection_name=collection,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )

        if not points:
            break

        for point in points:
            payload = point.payload or {}
            vector = point.vector

            if not vector:
                continue

            # Extraire les métadonnées du payload Qdrant
            doc_id = payload.get("doc_id", f"qdrant_migration/{point.id}")
            text = payload.get("text", "")
            if not text:
                continue

            source_path = payload.get("source", doc_id)
            if source_path not in source_groups:
                source_groups[source_path] = []

            source_groups[source_path].append({
                "point_id": str(point.id),
                "text": text,
                "embedding": list(vector) if not isinstance(vector, list) else vector,
                "payload": payload,
                "index": len(source_groups[source_path]),
            })

        if next_offset is None:
            break
        offset = next_offset

    logger.info("%d sources distinctes identifiées à partir de %d points", len(source_groups), sum(len(v) for v in source_groups.values()))

    # Insérer dans pgvector
    for source_path, chunks in source_groups.items():
        async with pool.acquire() as conn:
            doc_uuid = str(uuid.uuid4())
            first_payload = chunks[0]["payload"]
            title = first_payload.get("title", first_payload.get("section", source_path))

            metadata = {
                "migrated_from": "qdrant",
                "collection": collection,
                "niveau": first_payload.get("niveau", ""),
                "matiere": first_payload.get("matiere", ""),
                "section": first_payload.get("section", ""),
            }

            try:
                await conn.execute(
                    """
                    INSERT INTO rag_documents
                        (id, tenant, source_type, source_path, title,
                         embed_model, embed_dim, chunk_count, metadata)
                    VALUES ($1::uuid, $2, 'migration', $3, $4, $5, $6, $7, $8::jsonb)
                    ON CONFLICT (source_path, tenant) DO UPDATE SET
                        title = EXCLUDED.title,
                        chunk_count = EXCLUDED.chunk_count,
                        updated_at = NOW()
                    """,
                    doc_uuid,
                    tenant,
                    source_path,
                    title,
                    embed_model,
                    embed_dim,
                    len(chunks),
                    json.dumps(metadata),
                )
            except Exception as exc:
                logger.warning("Erreur document %s: %s", source_path, exc)
                continue

            for chunk in chunks:
                emb_str = f"[{','.join(map(str, chunk['embedding']))}]"
                try:
                    await conn.execute(
                        """
                        INSERT INTO rag_chunks
                            (document_id, tenant, chunk_index, text, embedding, metadata)
                        VALUES ($1::uuid, $2, $3, $4, $5::vector, $6::jsonb)
                        ON CONFLICT (document_id, chunk_index) DO NOTHING
                        """,
                        doc_uuid,
                        tenant,
                        chunk["index"],
                        chunk["text"],
                        emb_str,
                        json.dumps(chunk["payload"]),
                    )
                    total_migrated += 1
                except Exception as exc:
                    logger.warning("Erreur chunk %s/%d: %s", source_path, chunk["index"], exc)

        if total_migrated % 100 == 0 and total_migrated > 0:
            logger.info("Progression : %d chunks migrés", total_migrated)

    await pool.close()
    logger.info("\n✅ Migration Qdrant terminée. Total : %d chunks migrés.", total_migrated)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migration Qdrant → pgvector")
    parser.add_argument("--qdrant-url", default="http://localhost:6333", help="URL Qdrant")
    parser.add_argument("--collection", default="programmes_vf", help="Collection Qdrant")
    parser.add_argument("--pg-dsn", required=True, help="DSN PostgreSQL")
    parser.add_argument("--tenant", default="nexus", help="Tenant cible")
    parser.add_argument("--embed-model", default="nomic-embed-text:v1.5", help="Modèle d'embedding")
    parser.add_argument("--embed-dim", type=int, default=768, help="Dimension des vecteurs")
    parser.add_argument("--batch-size", type=int, default=100, help="Taille des batchs Qdrant")
    args = parser.parse_args()

    asyncio.run(
        migrate(
            qdrant_url=args.qdrant_url,
            collection=args.collection,
            pg_dsn=args.pg_dsn,
            tenant=args.tenant,
            embed_model=args.embed_model,
            embed_dim=args.embed_dim,
            batch_size=args.batch_size,
        )
    )
