from __future__ import annotations

from scripts.backfill_dedicated_collection import build_where, select_rows_for_backfill


def test_build_where_with_multiple_filters() -> None:
    where = build_where({
        "matiere": "Mathématiques",
        "niveau": "Première",
        "groupe": "Enseignements de spécialité (EDS)",
    })

    assert where == {
        "$and": [
            {"matiere": "Mathématiques"},
            {"niveau": "Première"},
            {"groupe": "Enseignements de spécialité (EDS)"},
        ]
    }


def test_select_rows_for_backfill_rewrites_collection_metadata() -> None:
    rows = {
        "ids": ["chunk-1", "chunk-2"],
        "documents": ["alpha", "beta"],
        "metadatas": [
            {"collection": "rag_education", "section": "education", "sha256": "a"},
            {"collection": "rag_education", "section": "education", "sha256": "b"},
        ],
        "embeddings": [[0.1, 0.2], [0.3, 0.4]],
    }

    ids_to_add, docs_to_add, metas_to_add, embs_to_add = select_rows_for_backfill(
        rows=rows,
        target_collection="rag_maths_premiere",
        target_section="maths_premiere",
        existing_ids={"chunk-2"},
    )

    assert ids_to_add == ["chunk-1"]
    assert docs_to_add == ["alpha"]
    assert metas_to_add == [
        {"collection": "rag_maths_premiere", "section": "maths_premiere", "sha256": "a"}
    ]
    assert embs_to_add == [[0.1, 0.2]]
