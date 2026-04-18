"""
Tâches Celery pour ingestion asynchrone.
Évite les timeouts HTTP sur les gros fichiers.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from pathlib import Path
from typing import Any

from celery import Celery

logger = logging.getLogger(__name__)

celery_app = Celery(
    "rag_tasks",
    broker=os.getenv("REDIS_URL", "redis://redis:6379/0"),
    backend=os.getenv("REDIS_URL", "redis://redis:6379/0"),
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_time_limit=1800,  # 30 min max par tâche
    task_soft_time_limit=1500,  # soft limit 25 min
    worker_prefetch_multiplier=1,  # 1 tâche par worker à la fois
    result_expires=3600,  # résultats expirent après 1h
)


def _get_file_hash(file_path: str) -> str:
    """Calcule le SHA256 d'un fichier."""
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _get_text_hash(text: str) -> str:
    """Calcule le SHA256 d'un texte."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def _run_ingestion(
    tenant: str,
    source_type: str,
    source_path: str,
    options: dict[str, Any],
) -> dict[str, Any]:
    """Pipeline d'ingestion async complet.

    Args:
        tenant: Identifiant du tenant.
        source_type: Type de source (url, pdf, markdown, etc.).
        source_path: Chemin ou URL de la source.
        options: Options supplémentaires (title, label, metadata).

    Returns:
        Dict avec status, document_id, chunk_count.
    """
    from database import RagDatabase
    from embedding_service import EmbeddingService

    dsn = os.getenv("DATABASE_URL_SYNC", "postgresql://raguser:pass@pgvector:5432/ragdb")
    # asyncpg needs the async DSN
    async_dsn = dsn.replace("postgresql://", "postgresql://").replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    if "asyncpg" not in async_dsn:
        async_dsn = async_dsn.replace("postgresql://", "postgresql://")

    db = RagDatabase(async_dsn)
    await db.connect(min_size=2, max_size=5)

    embed_svc = EmbeddingService(
        ollama_url=os.getenv("OLLAMA_BASE_URL", os.getenv("OLLAMA_URL", "http://ollama:11434")),
        model=os.getenv("EMBED_MODEL", "nomic-embed-text:v1.5"),
    )
    await embed_svc.connect()

    try:
        # 1. Charger le texte source
        text = _load_source_text(source_type, source_path)
        if not text.strip():
            return {"status": "empty", "document_id": None, "chunk_count": 0}

        # 2. Chunking
        chunks_text = _smart_chunk(text, source_type)
        if not chunks_text:
            return {"status": "empty", "document_id": None, "chunk_count": 0}

        # 3. Vérifier déduplication par file_hash
        file_hash = _get_text_hash(text)
        existing_doc = await db.document_exists_by_hash(file_hash, tenant)
        if existing_doc and not options.get("force_reingest"):
            logger.info(
                "Document déjà ingéré (hash=%s, doc_id=%s), skip.",
                file_hash[:12], existing_doc,
            )
            return {
                "status": "duplicate",
                "document_id": existing_doc,
                "chunk_count": 0,
                "detail": "Document déjà ingéré (même hash). Utilisez force_reingest=true pour forcer.",
            }

        # 4. Upsert document
        embed_model = os.getenv("EMBED_MODEL", "nomic-embed-text:v1.5")
        embed_dim = int(os.getenv("EMBED_DIM", "768"))

        doc_id = await db.upsert_document(
            tenant=tenant,
            source_type=source_type,
            source_path=source_path,
            title=options.get("title", Path(source_path).stem if source_path else "untitled"),
            file_hash=file_hash,
            embed_model=embed_model,
            embed_dim=embed_dim,
            label=options.get("label"),
            char_count=len(text),
            metadata=options.get("metadata", {}),
        )

        # 4. Embed chunks
        embeddings = await embed_svc.embed_batch([c for c in chunks_text])

        # 5. Insert chunks
        chunk_records = []
        char_offset = 0
        for idx, (chunk_text, emb) in enumerate(zip(chunks_text, embeddings, strict=True)):
            chunk_records.append({
                "chunk_index": idx,
                "text": chunk_text,
                "embedding": emb,
                "char_start": char_offset,
                "char_end": char_offset + len(chunk_text),
                "metadata": {"source_type": source_type},
            })
            char_offset += len(chunk_text)

        inserted = await db.insert_chunks(doc_id, tenant, chunk_records)

        return {
            "status": "success",
            "document_id": doc_id,
            "chunk_count": inserted,
            "cache_stats": embed_svc.cache_stats,
        }
    finally:
        await embed_svc.disconnect()
        await db.disconnect()


def _load_source_text(source_type: str, source_path: str) -> str:
    """Charge le texte brut depuis une source.

    Args:
        source_type: Type de source.
        source_path: Chemin ou URL.

    Returns:
        Texte brut extrait.
    """
    if source_type in {"markdown", "md"}:
        return Path(source_path).read_text(encoding="utf-8", errors="ignore")

    if source_type == "pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(source_path)
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except ImportError:
            from langchain_community.document_loaders import PyPDFLoader
            docs = PyPDFLoader(source_path).load()
            return "\n".join(d.page_content for d in docs)

    if source_type == "docx":
        import docx
        d = docx.Document(source_path)
        return "\n".join(p.text for p in d.paragraphs if p.text.strip())

    if source_type == "url":
        import requests
        from bs4 import BeautifulSoup
        resp = requests.get(source_path, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        return soup.get_text("\n", strip=True)

    # Fallback: lire comme texte
    return Path(source_path).read_text(encoding="utf-8", errors="ignore")


def _smart_chunk(text: str, source_type: str) -> list[str]:
    """Chunking adaptatif selon le type de source.

    Args:
        text: Texte brut à découper.
        source_type: Type de source pour adapter la stratégie.

    Returns:
        Liste de chunks textuels.
    """
    from langchain.text_splitter import RecursiveCharacterTextSplitter

    max_chunk = int(os.getenv("MAX_CHUNK_SIZE", "1000"))
    overlap = int(os.getenv("CHUNK_OVERLAP", "200"))

    if source_type in {"markdown", "md"}:
        splitter = RecursiveCharacterTextSplitter(
            separators=["## ", "### ", "\n\n", "\n", " "],
            chunk_size=max_chunk,
            chunk_overlap=min(overlap, max_chunk // 4),
            length_function=len,
        )
    elif source_type == "pdf":
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=max_chunk,
            chunk_overlap=overlap,
        )
    else:
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=int(max_chunk * 0.8),
            chunk_overlap=int(overlap * 0.6),
        )

    chunks = splitter.split_text(text)
    # Filtrer les chunks trop courts (< 50 chars = bruit)
    return [c for c in chunks if len(c.strip()) >= 50]


@celery_app.task(bind=True, name="ingest_document", max_retries=3)
def ingest_document_task(
    self: Any,
    tenant: str,
    source_type: str,
    source_path: str,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Tâche d'ingestion asynchrone Celery.

    Args:
        tenant: Identifiant du tenant.
        source_type: Type de source (url, pdf, markdown, etc.).
        source_path: Chemin ou URL de la source.
        options: Options supplémentaires (title, label, metadata).

    Returns:
        Dict avec status et détails de l'ingestion.
    """
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(
            _run_ingestion(tenant, source_type, source_path, options or {})
        )
        loop.close()
        return {"status": "success", **result}
    except Exception as exc:
        logger.exception("Ingestion task failed for %s/%s", tenant, source_path)
        countdown = 60 * (self.request.retries + 1)
        raise self.retry(exc=exc, countdown=countdown) from exc
