"""Tests unitaires pour le hybrid search (RRF + reranking)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Ensure src/ingestor is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "ingestor"))

from hybrid_search import SearchResult, reciprocal_rank_fusion


def make_result(id: str, score: float) -> dict[str, Any]:
    """Helper pour créer un résultat de recherche factice."""
    return {
        "id": id,
        "document_id": f"doc_{id}",
        "chunk_index": 0,
        "text": f"Texte du chunk {id}",
        "score": score,
        "title": f"Doc {id}",
        "source_path": f"/path/{id}",
        "source_type": "markdown",
        "page_number": None,
        "metadata": {},
    }


def test_rrf_boosts_results_in_both_lists() -> None:
    """Un résultat dans les deux listes doit avoir un score plus élevé."""
    dense = [make_result("a", 0.9), make_result("b", 0.8), make_result("c", 0.7)]
    sparse = [make_result("b", 0.95), make_result("d", 0.85), make_result("a", 0.75)]

    results = reciprocal_rank_fusion(dense, sparse)
    ids = [r.id for r in results]

    # 'a' et 'b' sont dans les deux listes → doivent être en tête
    assert ids[0] in ("a", "b")
    assert ids[1] in ("a", "b")


def test_rrf_alpha_weights() -> None:
    """alpha=1.0 → pure dense, alpha=0.0 → pure sparse."""
    dense = [make_result("dense_top", 0.99), make_result("b", 0.5)]
    sparse = [make_result("sparse_top", 0.99), make_result("b", 0.5)]

    pure_dense = reciprocal_rank_fusion(dense, sparse, alpha=1.0)
    pure_sparse = reciprocal_rank_fusion(dense, sparse, alpha=0.0)

    assert pure_dense[0].id == "dense_top"
    assert pure_sparse[0].id == "sparse_top"


def test_rrf_deduplication() -> None:
    """Les résultats présents dans les deux listes ne doivent pas être dupliqués."""
    dense = [make_result("a", 0.9), make_result("b", 0.8)]
    sparse = [make_result("a", 0.9), make_result("c", 0.8)]

    results = reciprocal_rank_fusion(dense, sparse)
    ids = [r.id for r in results]

    assert len(ids) == len(set(ids)), "Pas de doublons dans les résultats"
    assert len(ids) == 3  # a, b, c


def test_rrf_empty_inputs() -> None:
    """RRF avec des listes vides ne doit pas crasher."""
    results = reciprocal_rank_fusion([], [])
    assert results == []

    results_dense_only = reciprocal_rank_fusion([make_result("a", 0.9)], [])
    assert len(results_dense_only) == 1
    assert results_dense_only[0].id == "a"


def test_rrf_returns_search_result_type() -> None:
    """Les résultats doivent être des instances de SearchResult."""
    dense = [make_result("a", 0.9)]
    sparse = [make_result("b", 0.8)]

    results = reciprocal_rank_fusion(dense, sparse)
    for r in results:
        assert isinstance(r, SearchResult)
        assert isinstance(r.id, str)
        assert isinstance(r.score, float)
        assert isinstance(r.text, str)


def test_rrf_score_ordering() -> None:
    """Les résultats doivent être triés par score RRF décroissant."""
    dense = [
        make_result("a", 0.9),
        make_result("b", 0.8),
        make_result("c", 0.7),
        make_result("d", 0.6),
    ]
    sparse = [
        make_result("c", 0.95),
        make_result("a", 0.85),
        make_result("e", 0.75),
    ]

    results = reciprocal_rank_fusion(dense, sparse)
    scores = [r.score for r in results]

    # Vérifier que les scores sont décroissants
    for i in range(len(scores) - 1):
        assert scores[i] >= scores[i + 1], f"Score {scores[i]} < {scores[i+1]} à l'index {i}"


def test_rrf_preserves_metadata() -> None:
    """Les métadonnées doivent être préservées dans les résultats."""
    dense = [{
        "id": "x",
        "document_id": "doc_x",
        "chunk_index": 3,
        "text": "Contenu important",
        "score": 0.95,
        "title": "Mon document",
        "source_path": "/docs/test.md",
        "source_type": "markdown",
        "page_number": 5,
        "metadata": {"key": "value"},
    }]

    results = reciprocal_rank_fusion(dense, [])
    assert len(results) == 1
    r = results[0]
    assert r.document_id == "doc_x"
    assert r.chunk_index == 3
    assert r.title == "Mon document"
    assert r.source_path == "/docs/test.md"
    assert r.page_number == 5
