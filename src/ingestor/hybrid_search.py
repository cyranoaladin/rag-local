"""
Hybrid Search avec Reciprocal Rank Fusion (RRF).
Combine dense vector search + BM25 sparse search + reranking CrossEncoder.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from database import RagDatabase

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Résultat de recherche unifié (dense + sparse + reranked)."""

    id: str
    document_id: str
    chunk_index: int
    text: str
    score: float
    title: str = ""
    source_path: str = ""
    source_type: str = ""
    page_number: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    rerank_score: float | None = None


@lru_cache(maxsize=1)
def get_reranker() -> Any:
    """Charge le modèle CrossEncoder pour le reranking (singleton)."""
    from sentence_transformers import CrossEncoder

    model_name = os.getenv(
        "RERANKER_MODEL",
        "cross-encoder/ms-marco-MiniLM-L-6-v2",
    )
    logger.info("Loading reranker model: %s", model_name)
    return CrossEncoder(model_name, max_length=512)


def reciprocal_rank_fusion(
    dense_results: list[dict[str, Any]],
    sparse_results: list[dict[str, Any]],
    alpha: float = 0.7,
    k_rrf: int = 60,
) -> list[SearchResult]:
    """Fusionne dense + sparse via RRF.

    Args:
        dense_results: Résultats de la recherche vectorielle.
        sparse_results: Résultats de la recherche BM25.
        alpha: Poids du dense (0.7 = 70% dense, 30% sparse).
        k_rrf: Constante RRF (60 est le standard).

    Returns:
        Liste de SearchResult triée par score RRF décroissant.
    """
    scores: dict[str, float] = {}
    data: dict[str, dict[str, Any]] = {}

    for rank, row in enumerate(dense_results):
        chunk_id = str(row["id"])
        scores[chunk_id] = scores.get(chunk_id, 0) + alpha / (k_rrf + rank + 1)
        data[chunk_id] = row

    for rank, row in enumerate(sparse_results):
        chunk_id = str(row["id"])
        scores[chunk_id] = scores.get(chunk_id, 0) + (1 - alpha) / (k_rrf + rank + 1)
        if chunk_id not in data:
            data[chunk_id] = row

    sorted_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)

    return [
        SearchResult(
            id=cid,
            document_id=str(data[cid]["document_id"]),
            chunk_index=data[cid]["chunk_index"],
            text=data[cid]["text"],
            score=scores[cid],
            title=data[cid].get("title", ""),
            source_path=data[cid].get("source_path", ""),
            source_type=data[cid].get("source_type", ""),
            page_number=data[cid].get("page_number"),
            metadata=data[cid].get("metadata", {}),
        )
        for cid in sorted_ids
        if cid in data
    ]


def rerank(
    query: str,
    candidates: list[SearchResult],
    top_n: int = 5,
) -> list[SearchResult]:
    """Reranking CrossEncoder — re-score les candidats avec un modèle plus précis.

    Args:
        query: La requête utilisateur.
        candidates: Candidats issus du RRF.
        top_n: Nombre de résultats finaux à retourner.

    Returns:
        Les top_n candidats reranqués par score décroissant.
    """
    if not candidates:
        return []

    try:
        reranker = get_reranker()
        pairs = [(query, c.text) for c in candidates]
        raw_scores = reranker.predict(pairs, show_progress_bar=False)

        tolist = getattr(raw_scores, "tolist", None)
        scores_list = tolist() if callable(tolist) else list(raw_scores)

        if len(scores_list) != len(candidates):
            raise ValueError(
                "Reranker returned %d scores for %d candidates"
                % (len(scores_list), len(candidates))
            )

        for candidate, score in zip(candidates, scores_list, strict=True):
            candidate.rerank_score = float(score)

        candidates.sort(key=lambda c: c.rerank_score or 0.0, reverse=True)
        return candidates[:top_n]
    except Exception:
        logger.exception("Reranking failed, returning RRF results as-is")
        return candidates[:top_n]


async def hybrid_search_pipeline(
    query: str,
    query_embedding: list[float],
    tenant: str,
    db: RagDatabase,
    k: int = 10,
    alpha: float = 0.7,
    rerank_top_n: int = 5,
    use_rerank: bool = True,
    filters: dict[str, Any] | None = None,
) -> list[SearchResult]:
    """Pipeline complet : dense + sparse + RRF + rerank.

    Args:
        query: Texte de la requête.
        query_embedding: Vecteur d'embedding de la requête.
        tenant: Identifiant du tenant.
        db: Instance RagDatabase.
        k: Nombre de résultats souhaités avant reranking.
        alpha: Poids dense vs sparse (0.0-1.0).
        rerank_top_n: Nombre de résultats après reranking.
        use_rerank: Activer/désactiver le reranking.
        filters: Filtres optionnels (document_id, source_type).

    Returns:
        Liste de SearchResult triée par pertinence.
    """
    # 1. Recherches parallèles
    dense_task = asyncio.create_task(
        db.dense_search(query_embedding, tenant, k=k * 3, filters=filters)
    )
    sparse_task = asyncio.create_task(
        db.sparse_search(query, tenant, k=k * 3)
    )
    dense_results, sparse_results = await asyncio.gather(dense_task, sparse_task)

    logger.debug(
        "Hybrid search: %d dense, %d sparse results",
        len(dense_results),
        len(sparse_results),
    )

    # 2. Fusion RRF
    fused = reciprocal_rank_fusion(dense_results, sparse_results, alpha=alpha)
    candidates = fused[: k * 2]

    # 3. Reranking (optionnel)
    if use_rerank and candidates:
        return rerank(query, candidates, top_n=rerank_top_n)

    return candidates[:k]
