"""Backfill a dedicated Chroma collection from an existing source collection.

Example:
    python scripts/backfill_dedicated_collection.py \
        --source rag_education \
        --target rag_maths_premiere \
        --section maths_premiere \
        --filter matiere=Mathématiques \
        --filter niveau=Première \
        --filter "groupe=Enseignements de spécialité (EDS)"
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from typing import Any

import chromadb


def build_where(filters: Mapping[str, str]) -> dict[str, Any]:
    """Build a Chroma where clause from key/value filters."""
    conditions = [{key: value} for key, value in filters.items() if value]
    if not conditions:
        return {}
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def rewrite_metadata(
    metadata: Mapping[str, Any] | None,
    *,
    target_collection: str,
    target_section: str,
) -> dict[str, Any]:
    """Rewrite collection-specific metadata for the destination collection."""
    rewritten = dict(metadata or {})
    rewritten["collection"] = target_collection
    rewritten["section"] = target_section
    return rewritten


def select_rows_for_backfill(
    *,
    rows: Mapping[str, Sequence[Any]],
    target_collection: str,
    target_section: str,
    existing_ids: set[str],
) -> tuple[list[str], list[str], list[dict[str, Any]], list[Any]]:
    """Return rows that still need to be inserted in the target collection."""
    ids = list(rows.get("ids") or [])
    documents = list(rows.get("documents") or [])
    metadatas = list(rows.get("metadatas") or [])
    raw_embeddings = rows.get("embeddings")
    embeddings = list(raw_embeddings) if raw_embeddings is not None else []

    ids_to_add: list[str] = []
    docs_to_add: list[str] = []
    metas_to_add: list[dict[str, Any]] = []
    embs_to_add: list[Any] = []

    for idx, chunk_id in enumerate(ids):
        if chunk_id in existing_ids:
            continue
        ids_to_add.append(chunk_id)
        docs_to_add.append(str(documents[idx]))
        metas_to_add.append(
            rewrite_metadata(
                metadatas[idx] if idx < len(metadatas) else None,
                target_collection=target_collection,
                target_section=target_section,
            )
        )
        emb = embeddings[idx] if idx < len(embeddings) else None
        if hasattr(emb, "tolist"):
            emb = emb.tolist()
        embs_to_add.append(emb)

    return ids_to_add, docs_to_add, metas_to_add, embs_to_add


def backfill_collection(
    *,
    chroma_host: str,
    chroma_port: int,
    source_collection: str,
    target_collection: str,
    target_section: str,
    filters: Mapping[str, str],
    batch_size: int = 100,
    dry_run: bool = False,
) -> dict[str, int]:
    """Copy matching chunks from a source collection into a dedicated collection."""
    client = chromadb.HttpClient(host=chroma_host, port=chroma_port)
    source = client.get_or_create_collection(
        name=source_collection,
        metadata={"hnsw:space": "cosine"},
    )
    target = client.get_or_create_collection(
        name=target_collection,
        metadata={"hnsw:space": "cosine"},
    )

    rows = source.get(
        where=build_where(filters),
        include=["documents", "metadatas", "embeddings"],
    )
    ids = list(rows.get("ids") or [])
    existing_ids = set((target.get(ids=ids) or {}).get("ids", [])) if ids else set()
    ids_to_add, docs_to_add, metas_to_add, embs_to_add = select_rows_for_backfill(
        rows=rows,
        target_collection=target_collection,
        target_section=target_section,
        existing_ids=existing_ids,
    )

    if not dry_run:
        for start in range(0, len(ids_to_add), batch_size):
            target.add(
                ids=ids_to_add[start:start + batch_size],
                documents=docs_to_add[start:start + batch_size],
                metadatas=metas_to_add[start:start + batch_size],
                embeddings=embs_to_add[start:start + batch_size],
            )

    return {
        "source_matches": len(ids),
        "preexisting": len(existing_ids),
        "added": 0 if dry_run else len(ids_to_add),
        "target_count": target.count() if not dry_run else target.count(),
    }


def _parse_filter(raw_value: str) -> tuple[str, str]:
    if "=" not in raw_value:
        raise argparse.ArgumentTypeError("Expected KEY=VALUE")
    key, value = raw_value.split("=", 1)
    key = key.strip()
    value = value.strip()
    if not key or not value:
        raise argparse.ArgumentTypeError("Expected KEY=VALUE")
    return key, value


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill a dedicated Chroma collection from a source collection.")
    parser.add_argument("--chroma-host", default="localhost", help="Chroma host")
    parser.add_argument("--chroma-port", type=int, default=8000, help="Chroma port")
    parser.add_argument("--source", required=True, help="Source collection name")
    parser.add_argument("--target", required=True, help="Target collection name")
    parser.add_argument("--section", required=True, help="Target section metadata value")
    parser.add_argument(
        "--filter",
        dest="filters",
        action="append",
        type=_parse_filter,
        default=[],
        help="Metadata filter as KEY=VALUE. May be repeated.",
    )
    parser.add_argument("--batch-size", type=int, default=100, help="Number of chunks per add batch")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be copied without writing")
    args = parser.parse_args()

    summary = backfill_collection(
        chroma_host=args.chroma_host,
        chroma_port=args.chroma_port,
        source_collection=args.source,
        target_collection=args.target,
        target_section=args.section,
        filters=dict(args.filters),
        batch_size=args.batch_size,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
