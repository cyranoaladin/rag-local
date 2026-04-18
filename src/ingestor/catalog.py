from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

DB_PATH = os.getenv("ADMIN_DB_PATH", "/data/catalog.sqlite")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def db_conn(path: str | None = None):
    path = path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(path: str | None = None) -> None:
    with db_conn(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS documents (
              id TEXT PRIMARY KEY,
              domain TEXT NOT NULL,
              title TEXT,
              source_type TEXT NOT NULL,
              source_location TEXT NOT NULL,
              tags TEXT,
              metadata_json TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              last_ingest_at TEXT,
              last_ingest_status TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ingestion_runs (
              id TEXT PRIMARY KEY,
              document_id TEXT NOT NULL,
              started_at TEXT NOT NULL,
              finished_at TEXT,
              status TEXT NOT NULL,
              error_message TEXT,
              chunks_count INTEGER,
              FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
            )
            """
        )


@dataclass
class Document:
    id: str
    domain: str
    title: str | None
    source_type: str
    source_location: str
    tags: list[str]
    metadata: dict[str, Any]
    created_at: str
    updated_at: str
    last_ingest_at: str | None
    last_ingest_status: str | None


def _row_to_document(row: tuple[Any, ...]) -> dict[str, Any]:
    (
        id_, domain, title, source_type, source_location,
        tags, metadata_json, created_at, updated_at, last_ingest_at, last_ingest_status
    ) = row
    return {
        "id": id_,
        "domain": domain,
        "title": title,
        "source_type": source_type,
        "source_location": source_location,
        "tags": (tags.split(",") if tags else []),
        "metadata": (json.loads(metadata_json) if metadata_json else {}),
        "created_at": created_at,
        "updated_at": updated_at,
        "last_ingest_at": last_ingest_at,
        "last_ingest_status": last_ingest_status,
    }


def create_document(
    domain: str,
    source_type: str,
    source_location: str,
    title: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    *,
    path: str | None = None,
) -> dict[str, Any]:
    init_db(path)
    doc_id = str(uuid.uuid4())
    now = _utc_now()
    tags_csv = ",".join([t.strip() for t in (tags or []) if t and t.strip()]) or None
    metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
    with db_conn(path) as conn:
        conn.execute(
            """
            INSERT INTO documents (
              id, domain, title, source_type, source_location, tags,
              metadata_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                doc_id, domain, title, source_type, source_location, tags_csv,
                metadata_json, now, now,
            ),
        )
        row = conn.execute(
            "SELECT id, domain, title, source_type, source_location, tags, metadata_json, created_at, updated_at, last_ingest_at, last_ingest_status FROM documents WHERE id = ?",
            (doc_id,),
        ).fetchone()
    return _row_to_document(row)


def list_documents(
    *, domain: str | None = None, limit: int = 200, path: str | None = None
) -> list[dict[str, Any]]:
    init_db(path)
    q = (
        "SELECT id, domain, title, source_type, source_location, tags, metadata_json, created_at, updated_at, last_ingest_at, last_ingest_status FROM documents"
    )
    params: list[Any] = []
    if domain:
        q += " WHERE domain = ?"
        params.append(domain)
    q += " ORDER BY updated_at DESC LIMIT ?"
    params.append(int(max(1, min(limit, 1000))))
    with db_conn(path) as conn:
        rows = conn.execute(q, params).fetchall()
    return [_row_to_document(r) for r in rows]


def get_document(document_id: str, *, path: str | None = None) -> dict[str, Any] | None:
    init_db(path)
    with db_conn(path) as conn:
        row = conn.execute(
            "SELECT id, domain, title, source_type, source_location, tags, metadata_json, created_at, updated_at, last_ingest_at, last_ingest_status FROM documents WHERE id = ?",
            (document_id,),
        ).fetchone()
    return _row_to_document(row) if row else None


@dataclass
class IngestionRun:
    id: str
    document_id: str
    started_at: str
    finished_at: str | None
    status: str
    error_message: str | None
    chunks_count: int | None


def create_ingestion_run(document_id: str, *, path: str | None = None) -> dict[str, Any]:
    init_db(path)
    run_id = str(uuid.uuid4())
    now = _utc_now()
    with db_conn(path) as conn:
        # ensure doc exists
        doc = conn.execute("SELECT id FROM documents WHERE id = ?", (document_id,)).fetchone()
        if not doc:
            raise ValueError(f"Unknown document_id: {document_id}")
        conn.execute(
            """
            INSERT INTO ingestion_runs (id, document_id, started_at, status)
            VALUES (?, ?, ?, ?)
            """,
            (run_id, document_id, now, "in_progress"),
        )
    return {
        "id": run_id,
        "document_id": document_id,
        "started_at": now,
        "finished_at": None,
        "status": "in_progress",
        "error_message": None,
        "chunks_count": None,
    }


def finish_ingestion_run(
    run_id: str,
    *,
    status: str,
    error_message: str | None = None,
    chunks_count: int | None = None,
    path: str | None = None,
) -> dict[str, Any] | None:
    finish_ts = _utc_now()
    init_db(path)
    with db_conn(path) as conn:
        run = conn.execute("SELECT document_id FROM ingestion_runs WHERE id = ?", (run_id,)).fetchone()
        if not run:
            return None
        (document_id,) = run
        conn.execute(
            """
            UPDATE ingestion_runs SET finished_at = ?, status = ?, error_message = ?, chunks_count = ?
            WHERE id = ?
            """,
            (finish_ts, status, error_message, chunks_count, run_id),
        )
        # update doc summary
        conn.execute(
            "UPDATE documents SET last_ingest_at = ?, last_ingest_status = ?, updated_at = ? WHERE id = ?",
            (finish_ts, status, finish_ts, document_id),
        )
        row = conn.execute(
            "SELECT id, document_id, started_at, finished_at, status, error_message, chunks_count FROM ingestion_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
    if not row:
        return None
    (rid, doc_id, started_at, finished_at, st, err, chunks) = row
    return {
        "id": rid,
        "document_id": doc_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "status": st,
        "error_message": err,
        "chunks_count": chunks,
    }


def list_ingestions(document_id: str, *, limit: int = 50, path: str | None = None) -> list[dict[str, Any]]:
    init_db(path)
    with db_conn(path) as conn:
        rows = conn.execute(
            """
            SELECT id, document_id, started_at, finished_at, status, error_message, chunks_count
            FROM ingestion_runs WHERE document_id = ?
            ORDER BY started_at DESC LIMIT ?
            """,
            (document_id, int(max(1, min(limit, 1000)))),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for (rid, doc_id, started_at, finished_at, status, err, chunks) in rows:
        out.append({
            "id": rid,
            "document_id": doc_id,
            "started_at": started_at,
            "finished_at": finished_at,
            "status": status,
            "error_message": err,
            "chunks_count": chunks,
        })
    return out


def update_document(
    document_id: str,
    *,
    title: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    path: str | None = None,
) -> dict[str, Any] | None:
    """Update allowed fields only (title, tags, metadata). Domain/source_* are immutable.
    Returns the updated document dict or None if not found.
    """
    init_db(path)
    fields: list[str] = []
    params: list[Any] = []
    if title is not None:
        fields.append("title = ?")
        params.append(title)
    if tags is not None:
        tags_csv = ",".join([str(t).strip() for t in tags if t and str(t).strip()]) or None
        fields.append("tags = ?")
        params.append(tags_csv)
    if metadata is not None:
        metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
        fields.append("metadata_json = ?")
        params.append(metadata_json)
    if not fields:
        return get_document(document_id, path=path)
    fields.append("updated_at = ?")
    params.append(_utc_now())
    params.append(document_id)
    with db_conn(path) as conn:
        conn.execute(f"UPDATE documents SET {', '.join(fields)} WHERE id = ?", params)
    return get_document(document_id, path=path)


def delete_document(document_id: str, *, path: str | None = None) -> bool:
    """Delete a document by id. ON DELETE CASCADE removes related ingestion_runs."""
    init_db(path)
    with db_conn(path) as conn:
        from typing import cast
        cur = conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        return cast(int, cur.rowcount) > 0


def list_all_ingestions(
    *,
    document_id: str | None = None,
    status: str | None = None,
    since: str | None = None,
    limit: int = 200,
    path: str | None = None,
) -> list[dict[str, Any]]:
    """Return list of ingestion_runs with optional filters across all documents."""
    init_db(path)
    clauses: list[str] = []
    params: list[Any] = []
    if document_id:
        clauses.append("document_id = ?")
        params.append(document_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if since:
        clauses.append("started_at >= ?")
        params.append(since)
    q = (
        "SELECT id, document_id, started_at, finished_at, status, error_message, chunks_count FROM ingestion_runs"
    )
    if clauses:
        q += " WHERE " + " AND ".join(clauses)
    q += " ORDER BY started_at DESC LIMIT ?"
    params.append(int(max(1, min(limit, 1000))))
    with db_conn(path) as conn:
        rows = conn.execute(q, params).fetchall()
    out: list[dict[str, Any]] = []
    for (rid, doc_id, started_at, finished_at, st, err, chunks) in rows:
        out.append({
            "id": rid,
            "document_id": doc_id,
            "started_at": started_at,
            "finished_at": finished_at,
            "status": st,
            "error_message": err,
            "chunks_count": chunks,
        })
    return out
