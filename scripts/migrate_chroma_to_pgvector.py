"""
Script de migration ChromaDB → pgvector.
Lit les embeddings depuis ChromaDB et les réinsère dans pgvector
SANS les recalculer (préserve la cohérence vectorielle).

Usage :
    python migrate_chroma_to_pgvector.py \
        --chroma-host localhost --chroma-port 8000 \
        --pg-dsn "postgresql://raguser:pass@localhost:5435/ragdb" \
        --tenant nsi
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import uuid
from typing import Any

import asyncpg

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


async def migrate(
    chroma_host: str,
    chroma_port: int,
    pg_dsn: str,
    tenant: str,
    embed_model: str,
    embed_dim: int,
    chroma_path: str | None = None,
) -> None:
    """Migre toutes les collections ChromaDB vers pgvector.

    Args:
        chroma_host: Hôte ChromaDB (vide pour mode persistant local).
        chroma_port: Port ChromaDB.
        pg_dsn: DSN PostgreSQL.
        tenant: Identifiant du tenant cible.
        embed_model: Nom du modèle d'embedding utilisé.
        embed_dim: Dimension des vecteurs.
        chroma_path: Chemin local ChromaDB (mode persistant).
    """
    import chromadb

    # Connexion ChromaDB
    if chroma_host:
        client = chromadb.HttpClient(host=chroma_host, port=chroma_port)
    elif chroma_path:
        client = chromadb.PersistentClient(path=chroma_path)
    else:
        logger.error("Spécifier --chroma-host ou --chroma-path")
        sys.exit(1)

    collections = client.list_collections()
    coll_names = []
    for c in collections:
        if isinstance(c, str):
            coll_names.append(c)
        elif hasattr(c, "name"):
            coll_names.append(c.name)
        else:
            coll_names.append(str(c))

    logger.info("Collections ChromaDB trouvées : %s", coll_names)

    # Connexion pgvector
    pool = await asyncpg.create_pool(pg_dsn, min_size=2, max_size=10)

    total_migrated = 0

    for coll_name in coll_names:
        logger.info("Migration de la collection : %s", coll_name)
        try:
            collection = client.get_collection(coll_name)
        except Exception as exc:
            logger.warning("Impossible d'ouvrir la collection %s: %s", coll_name, exc)
            continue

        # Récupérer toutes les données
        try:
            data = collection.get(include=["documents", "embeddings", "metadatas"])
        except Exception as exc:
            logger.warning("Impossible de lire la collection %s: %s", coll_name, exc)
            continue

        ids = data.get("ids", [])
        texts = data.get("documents", [])
        embeddings = data.get("embeddings", [])
        metadatas = data.get("metadatas", [])

        if not ids:
            logger.info("  Collection %s vide, skip.", coll_name)
            continue

        logger.info("  %d chunks à migrer...", len(ids))

        # Regrouper par source pour créer des documents
        source_groups: dict[str, list[dict[str, Any]]] = {}
        for text_id, text, emb, meta in zip(
            ids,
            texts or [None] * len(ids),
            embeddings or [None] * len(ids),
            metadatas or [{}] * len(ids),
            strict=True,
        ):
            if not text or not emb:
                continue
            source = (meta or {}).get("source", f"chroma_migration/{coll_name}/{text_id}")
            if source not in source_groups:
                source_groups[source] = []
            source_groups[source].append({
                "text_id": text_id,
                "text": text,
                "embedding": emb,
                "metadata": meta or {},
                "index": len(source_groups[source]),
            })

        logger.info("  %d sources distinctes identifiées", len(source_groups))

        for source_path, chunks in source_groups.items():
            async with pool.acquire() as conn:
                # Créer le document
                title = chunks[0]["metadata"].get("title", source_path)
                doc_id = str(uuid.uuid4())

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
                        RETURNING id
                        """,
                        doc_id,
                        tenant,
                        source_path,
                        title,
                        embed_model,
                        embed_dim,
                        len(chunks),
                        json.dumps({"migrated_from": "chromadb", "collection": coll_name}),
                    )
                except Exception as exc:
                    logger.warning("  Erreur document %s: %s", source_path, exc)
                    continue

                # Insérer les chunks
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
                            doc_id,
                            tenant,
                            chunk["index"],
                            chunk["text"],
                            emb_str,
                            json.dumps(chunk["metadata"]),
                        )
                        total_migrated += 1
                    except Exception as exc:
                        logger.warning("  Erreur chunk %s/%d: %s", source_path, chunk["index"], exc)

            if total_migrated % 100 == 0 and total_migrated > 0:
                logger.info("  Progression : %d chunks migrés", total_migrated)

        logger.info("  ✅ Collection %s migrée.", coll_name)

    await pool.close()
    logger.info("\n✅ Migration terminée. Total : %d chunks migrés.", total_migrated)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migration ChromaDB → pgvector")
    parser.add_argument("--chroma-host", default="", help="Hôte ChromaDB (HTTP mode)")
    parser.add_argument("--chroma-port", type=int, default=8000, help="Port ChromaDB")
    parser.add_argument("--chroma-path", default="", help="Chemin local ChromaDB (persistent mode)")
    parser.add_argument("--pg-dsn", required=True, help="DSN PostgreSQL")
    parser.add_argument("--tenant", default="nsi", help="Tenant cible")
    parser.add_argument("--embed-model", default="nomic-embed-text:v1.5", help="Modèle d'embedding")
    parser.add_argument("--embed-dim", type=int, default=768, help="Dimension des vecteurs")
    args = parser.parse_args()

    asyncio.run(
        migrate(
            chroma_host=args.chroma_host,
            chroma_port=args.chroma_port,
            pg_dsn=args.pg_dsn,
            tenant=args.tenant,
            embed_model=args.embed_model,
            embed_dim=args.embed_dim,
            chroma_path=args.chroma_path or None,
        )
    )
