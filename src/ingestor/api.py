# Fichier: /srv/rag/ingestor/api.py
from __future__ import annotations

import hashlib
import ipaddress
import os
import socket
import tempfile
import unicodedata
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Literal, Mapping, TypeAlias, cast
from urllib.parse import urlparse

import chromadb
import docx
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response
from langchain_community.document_loaders import PyPDFLoader
from langchain_community.embeddings import OllamaEmbeddings
from langchain_core.documents import Document
from langchain_google_community import GoogleDriveLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel, ConfigDict, Field
from .mm_adapter import parse_multimodal
from .metrics import (
    METRICS_ENABLED,
    REGISTRY,
    generate_latest,
    record_bytes,
    record_chunk,
    record_failure,
    record_request,
    record_success,
    track_latency,
)

# --- Configuration ---
CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
COLLECTION_NAME = "ressources_pedagogiques_terminale"
MAX_REMOTE_BYTES = int(os.getenv("MAX_REMOTE_BYTES", str(10 * 1024 * 1024)))
LOCAL_SOURCE_ROOT = Path(
    os.getenv("LOCAL_SOURCE_ROOT", "/data/uploads")).resolve()
ALLOW_UNRESTRICTED_LOCAL = os.getenv(
    "ALLOW_UNRESTRICTED_LOCAL", "false").lower() == "true"
URL_SCHEMES_ALLOWED = {"http", "https"}

MULTIMODAL_ENABLED = os.getenv("MULTIMODAL_ENABLED", "false").lower() == "true"
MM_PARSER_TIMEOUT = float(os.getenv("MM_PARSER_TIMEOUT", "60"))
MM_MAX_CHARS_PER_CHUNK = int(os.getenv("MM_MAX_CHARS_PER_CHUNK", "4000"))
MM_CACHE_DIR = os.getenv("MM_CACHE_DIR", str(LOCAL_SOURCE_ROOT))
SUPPORTED_MULTIMODAL_TYPES = {"pdf", "docx"}

DocLike: TypeAlias = Document | SimpleNamespace

app = FastAPI(title="RAG Ingestor API")

# --- Modèle de requête ---


class IngestRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    source_type: Literal["url", "gdrive_folder", "pdf", "docx"]
    source: str
    metadata_hints: Dict[str, str] = Field(default_factory=dict, alias="hints")

# --- Utilitaires ---


def normalize_metadata(d: Mapping[str, Any]) -> Dict[str, str]:
    normalized: Dict[str, str] = {}
    for raw_key, raw_value in d.items():
        if raw_value in (None, ""):
            continue
        key = str(raw_key).strip().lower().replace(" ", "_")
        normalized[key] = str(raw_value)
    return normalized


def get_content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _resolve_local_path(raw_path: str) -> Path:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = (LOCAL_SOURCE_ROOT / candidate).resolve()
    else:
        candidate = candidate.resolve()
    if not ALLOW_UNRESTRICTED_LOCAL and not str(candidate).startswith(str(LOCAL_SOURCE_ROOT)):
        raise HTTPException(
            status_code=400, detail="Chemin local en dehors de la zone autorisée")
    if not candidate.exists():
        raise HTTPException(status_code=400, detail="Fichier introuvable")
    if not candidate.is_file():
        raise HTTPException(
            status_code=400, detail="Le chemin indiqué n'est pas un fichier")
    return candidate


def load_docx(file_path: str):
    try:
        d = docx.Document(file_path)
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Impossible de lire le DOCX: {e}")
    texts = []
    for p in d.paragraphs:
        if p.text and p.text.strip():
            texts.append(p.text.strip())
    # (option simple; on pourra enrichir avec les tableaux si besoin)
    content = "\n".join(texts).strip()
    if not content:
        return []
    return [Document(page_content=content, metadata={"source": os.path.basename(file_path)})]


def _mime_for_source_type(source_type: str) -> str:
    if source_type == "pdf":
        return "application/pdf"
    if source_type == "docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return "application/octet-stream"


def _load_multimodal_documents(req: IngestRequest) -> list[DocLike]:
    local_path = _resolve_local_path(req.source)
    mime = _mime_for_source_type(req.source_type)
    with local_path.open("rb") as handle:
        mm_chunks = list(
            parse_multimodal(
                handle,
                filename=local_path.name,
                mime=mime,
                timeout_s=MM_PARSER_TIMEOUT,
                max_chars_per_chunk=MM_MAX_CHARS_PER_CHUNK,
                cache_dir=MM_CACHE_DIR,
            )
        )

    documents: list[DocLike] = []
    for chunk in mm_chunks:
        chunk_text = chunk.as_text().strip()
        if not chunk_text:
            continue
        metadata = dict(chunk.metadata)
        metadata.update(
            {
                "source": req.source,
                "source_type": req.source_type,
                "mm_modality": chunk.modality,
            }
        )
        try:
            doc = Document(page_content=chunk_text, metadata=metadata)
        except Exception:  # pragma: no cover - langchain stubs during tests
            doc = SimpleNamespace(page_content=chunk_text, metadata=metadata)
        documents.append(doc)
    return documents


def _validate_remote_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme.lower() not in URL_SCHEMES_ALLOWED:
        raise HTTPException(
            status_code=400, detail="Schéma d'URL non autorisé")
    if not parsed.hostname:
        raise HTTPException(status_code=400, detail="URL invalide")
    try:
        addr_info = socket.getaddrinfo(parsed.hostname, parsed.port or (
            443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise HTTPException(
            status_code=400, detail=f"Résolution DNS impossible: {exc}")
    for entry in addr_info:
        ip = ipaddress.ip_address(entry[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            raise HTTPException(
                status_code=400, detail="URL interne non autorisée")


def _download_to_temp(url: str, suffix: str) -> Path:
    _validate_remote_url(url)
    try:
        with requests.get(url, timeout=30, stream=True) as response:
            response.raise_for_status()
            total = 0
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_file:
                for chunk in response.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_REMOTE_BYTES:
                        raise HTTPException(
                            status_code=400, detail="Fichier distant trop volumineux")
                    tmp_file.write(chunk)
                return Path(tmp_file.name)
    except HTTPException:
        raise
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=400, detail=f"Téléchargement impossible: {exc}")


def _fetch_remote_text(url: str) -> tuple[str, str]:
    _validate_remote_url(url)
    try:
        with requests.get(url, timeout=30, allow_redirects=True, stream=True) as response:
            if response.history:
                for hop in response.history:
                    _validate_remote_url(hop.url)
            _validate_remote_url(response.url)
            declared_length = response.headers.get("content-length")
            if declared_length and int(declared_length) > MAX_REMOTE_BYTES:
                raise HTTPException(
                    status_code=400, detail="Réponse distante trop volumineuse")
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_REMOTE_BYTES:
                    raise HTTPException(
                        status_code=400, detail="Réponse distante trop volumineuse")
                chunks.append(chunk)
            encoding = response.encoding or "utf-8"
            text = b"".join(chunks).decode(encoding, errors="ignore")
            if not text.strip():
                raise HTTPException(
                    status_code=400, detail="Aucun contenu exploitable sur la page")
            return response.url, text
    except HTTPException:
        raise
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=400, detail=f"Téléchargement impossible: {exc}")


def load_from_url(url: str):
    if url.lower().endswith(".pdf"):
        tmp_path = _download_to_temp(url, suffix=".pdf")
        try:
            return PyPDFLoader(str(tmp_path)).load()
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass
    final_url, text = _fetch_remote_text(url)
    soup = BeautifulSoup(text, "html.parser")
    text = soup.get_text("\n", strip=True)
    if not text:
        raise HTTPException(
            status_code=400, detail="Aucun contenu exploitable sur la page")
    return [Document(page_content=text, metadata={"source": final_url})]

# --- Endpoint ---


@app.post("/ingest")
def ingest_data(req: IngestRequest, mode: str = Query("text")):
    route = "/ingest"
    method = "POST"
    record_request(route, method)
    total_bytes_added = 0

    normalized_mode = (mode or "text").lower()
    is_multimodal_mode = MULTIMODAL_ENABLED and normalized_mode == "multimodal"
    if is_multimodal_mode and req.source_type not in SUPPORTED_MULTIMODAL_TYPES:
        is_multimodal_mode = False
    ingest_modality = "multimodal" if is_multimodal_mode else "text"
    should_split = not is_multimodal_mode

    with track_latency(route):
        try:
            if is_multimodal_mode:
                docs = _load_multimodal_documents(req)
            elif req.source_type == "url":
                docs = load_from_url(req.source)
            elif req.source_type == "gdrive_folder":
                loader = GoogleDriveLoader(folder_id=req.source, recursive=True)
                docs = loader.load()
            elif req.source_type == "pdf":
                path = _resolve_local_path(req.source)
                docs = PyPDFLoader(str(path)).load()
            elif req.source_type == "docx":
                path = _resolve_local_path(req.source)
                docs = load_docx(str(path))
            else:
                raise HTTPException(
                    status_code=400, detail=f"source_type non géré: {req.source_type}")
        except HTTPException as exc:
            record_failure(_failure_reason_from_exception(exc))
            raise
        except Exception as e:
            failure_tag = "mm_adapter_error" if is_multimodal_mode else "load_error"
            detail_prefix = "Erreur multimodale" if is_multimodal_mode else "Erreur de chargement"
            record_failure(failure_tag)
            raise HTTPException(
                status_code=500, detail=f"{detail_prefix}: {e}")

        if not docs:
            record_success(ingest_modality)
            empty_message = "Aucun chunk multimodal produit." if is_multimodal_mode else "Aucun document chargé."
            return {"status": "ok", "message": empty_message}

        if should_split:
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=1000, chunk_overlap=150)
            chunks = splitter.split_documents(docs)
        else:
            chunks = docs

        if not chunks:
            record_success(ingest_modality)
            empty_chunk_msg = "Aucun chunk multimodal produit." if is_multimodal_mode else "Aucun chunk textuel après découpage."
            return {"status": "ok", "message": empty_chunk_msg}

        ids, documents, metadatas = [], [], []
        for ch in chunks:
            text = (ch.page_content or "").strip()
            if not text:
                continue
            content_hash = get_content_hash(text)
            merged = {
                "sha256": content_hash,
                "source_type": req.source_type,
                "source": req.source,
            }
            merged.update(ch.metadata or {})
            merged.update(req.metadata_hints or {})
            ids.append(content_hash)
            documents.append(text)
            metadatas.append(normalize_metadata(merged))

        if not ids:
            record_success(ingest_modality)
            return {"status": "ok", "message": "Aucun contenu éligible à l'ingestion."}

        try:
            client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
            collection = client.get_or_create_collection(
                name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"})

            existing = collection.get(ids=ids)
            existing_ids = set(existing.get("ids", []))

            to_add_idx = [i for i, _id in enumerate(
                ids) if _id not in existing_ids]
            if not to_add_idx:
                record_success(ingest_modality)
                return {"status": "ok", "added": 0, "skipped": len(ids)}

            emb = OllamaEmbeddings(model=EMBED_MODEL, base_url=OLLAMA_URL)
            docs_to_add = [documents[i] for i in to_add_idx]
            ids_to_add = [ids[i] for i in to_add_idx]
            meta_to_add = [metadatas[i] for i in to_add_idx]
            embs_to_add = emb.embed_documents(docs_to_add)

            collection.add(
                documents=docs_to_add,
                ids=ids_to_add,
                metadatas=cast(Any, meta_to_add),
                embeddings=embs_to_add,
            )

            for _ in docs_to_add:
                record_chunk(ingest_modality)

            total_bytes_added = sum(len(doc.encode("utf-8")) for doc in docs_to_add)
            record_bytes(total_bytes_added)

            record_success(ingest_modality)
            return {"status": "ok", "added": len(ids_to_add), "skipped": len(existing_ids)}
        except HTTPException as exc:
            record_failure(_failure_reason_from_exception(exc))
            raise
        except Exception as e:
            record_failure("chroma_error")
            raise HTTPException(
                status_code=500, detail=f"Erreur d'ingestion dans ChromaDB: {e}")


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.get("/metrics")
def metrics() -> Response:
    if not METRICS_ENABLED:
        raise HTTPException(status_code=404, detail="Metrics disabled")
    return PlainTextResponse(generate_latest(REGISTRY), media_type="text/plain; version=0.0.4")


def _failure_reason_from_exception(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, str):
        base = detail.split(":", 1)[0].strip().lower().replace(" ", "_")
        normalized = unicodedata.normalize("NFKD", base)
        ascii_base = normalized.encode("ascii", "ignore").decode("ascii")
        slug = "".join(ch for ch in ascii_base if ch.isalnum() or ch == "_")
        if slug:
            return slug[:64]
    return f"http_{exc.status_code}"
