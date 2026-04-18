from __future__ import annotations

import os
import tempfile

from src.ingestor import catalog as cat


def test_create_get_update_delete_document() -> None:
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "cat.sqlite")
        os.environ["ADMIN_DB_PATH"] = db
        # create
        d = cat.create_document(
            domain="lycee",
            source_type="markdown",
            source_location="/data/uploads/doc.md",
            title="Titre",
            tags=["a", "b"],
            metadata={"x": 1},
            path=db,
        )
        got = cat.get_document(d["id"], path=db)
        assert got and got["domain"] == "lycee"
        # update allowed fields
        up = cat.update_document(d["id"], title="Titre2", tags=["c"], metadata={"y": 2}, path=db)
        assert up and up["title"] == "Titre2"
        # delete
        ok = cat.delete_document(d["id"], path=db)
        assert ok is True
        assert cat.get_document(d["id"], path=db) is None


def test_runs_lifecycle_and_list_all() -> None:
    with tempfile.TemporaryDirectory() as td:
        db = os.path.join(td, "cat.sqlite")
        os.environ["ADMIN_DB_PATH"] = db
        d = cat.create_document(
            domain="web3",
            source_type="pdf",
            source_location="/data/uploads/a.pdf",
            title="A",
            path=db,
        )
        run = cat.create_ingestion_run(d["id"], path=db)
        # finish success
        cat.finish_ingestion_run(run["id"], status="success", chunks_count=5, path=db)
        runs = cat.list_all_ingestions(document_id=d["id"], status="success", path=db)
        assert isinstance(runs, list) and len(runs) == 1
        assert runs[0]["chunks_count"] == 5
