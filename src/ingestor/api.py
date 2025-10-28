"""FastAPI entrypoint for the ingestion service."""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import os
import socket
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Literal, Mapping, Sequence, cast
from urllib.parse import urlparse

import chromadb
import docx
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from chromadb.api.types import SparseVector
from langchain_community.document_loaders import PyPDFLoader
from langchain_community.embeddings import OllamaEmbeddings
from langchain_core.documents import Document
from langchain_google_community import GoogleDriveLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel, ConfigDict, Field

from mm_adapter import Chunk, MMConfig, yield_chunks_from_path
from schemas import IngestResponse


CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
COLLECTION_NAME = os.getenv(
    "COLLECTION_NAME", "ressources_pedagogiques_terminale"
)
MAX_REMOTE_BYTES = int(os.getenv("MAX_REMOTE_BYTES", str(10 * 1024 * 1024)))
LOCAL_SOURCE_ROOT = Path(os.getenv("LOCAL_SOURCE_ROOT", "/data/uploads")).resolve()
ALLOW_UNRESTRICTED_LOCAL = os.getenv("ALLOW_UNRESTRICTED_LOCAL", "false").lower() == "true"
URL_SCHEMES_ALLOWED = {"http", "https"}
DISALLOWED_UPLOAD_SUFFIXES = {".exe", ".bat", ".cmd", ".zip", ".tar", ".gz", ".7z"}
ALLOWED_UPLOAD_SUFFIXES = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
}
ALLOWED_UPLOAD_MIME = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/jpg",
}

LOGGER = logging.getLogger("rag.ingestor")
if not LOGGER.handlers:
    logging.basicConfig(level=logging.INFO)

app = FastAPI(title="RAG Ingestor API")


class IngestRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    source_type: Literal["url", "gdrive_folder", "pdf", "docx"]
    source: str
    metadata_hints: Dict[str, str] = Field(default_factory=dict, alias="hints")


MetadataValue = str | int | float | bool | SparseVector | None


def normalize_metadata(data: Dict[str, object]) -> Dict[str, MetadataValue]:
    converted: Dict[str, MetadataValue] = {}
    for key, value in data.items():
        if value in (None, ""):
            continue
        normalized_key = str(key).strip().lower().replace(" ", "_")
        converted[normalized_key] = _metadata_value(value)
    return converted


def _metadata_value(value: object) -> MetadataValue:
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return value.name
    return str(value)


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _current_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_suffix(filename: str | None) -> str:
    if not filename:
        return ""
    suffix = Path(filename).suffix.lower()
    if suffix in DISALLOWED_UPLOAD_SUFFIXES:
        raise HTTPException(status_code=400, detail="Type de fichier interdit")
    if suffix and suffix not in ALLOWED_UPLOAD_SUFFIXES:
        raise HTTPException(status_code=400, detail=f"Extension non prise en charge: {suffix}")
    return suffix


def _parse_mode(request: Request, mode: str) -> str:
    header_mode = request.headers.get("x-parse-mode")
    candidate = (header_mode or mode or "text").lower()
    return "multimodal" if candidate == "multimodal" else "text"


def _ip_allowlist() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    raw = os.getenv("INGEST_IP_ALLOWLIST", "").strip()
    if not raw:
        return []
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            LOGGER.warning("event=invalid_allowlist_entry entry=%s", item)
    return networks


def _enforce_security(request: Request, token: str | None) -> None:
    expected = os.getenv("INGESTOR_API_TOKEN")
    if expected and token != expected:
        raise HTTPException(status_code=401, detail="Token invalide")
    allowlist = _ip_allowlist()
    if not allowlist:
        return
    if not request.client or not request.client.host:
        raise HTTPException(status_code=403, detail="Adresse IP inconnue")
    client_ip = ipaddress.ip_address(request.client.host)
    if not any(client_ip in net for net in allowlist):
        raise HTTPException(status_code=403, detail="IP non autorisée")


async def _persist_upload(file: UploadFile, max_mb: int) -> tuple[Path, int]:
    suffix = _safe_suffix(file.filename)
    total = 0
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix or ".bin")
    try:
        while True:
            chunk = await file.read(1 << 18)
            if not chunk:
                break
            total += len(chunk)
            if total > max_mb * 1024 * 1024:
                raise HTTPException(status_code=413, detail="Fichier trop volumineux")
            tmp.write(chunk)
        return Path(tmp.name), total
    except Exception:
        try:
            tmp.close()
        finally:
            Path(tmp.name).unlink(missing_ok=True)
        raise
    finally:
        try:
            tmp.close()
        except Exception:
            pass


def _multimodal_enabled() -> bool:
    return _bool_env("MULTIMODAL_ENABLED", False)


def _build_mm_config() -> MMConfig:
    allowed = tuple(s.strip().lower() for s in os.getenv("MM_ALLOWED_SUFFIXES", "").split(",") if s.strip())
    return MMConfig(
        parser=os.getenv("MULTIMODAL_PARSER", "raganything"),
        max_chars_per_chunk=int(os.getenv("MM_MAX_CHARS_PER_CHUNK", "8000")),
        caption_with_vlm=_bool_env("VLM_ENABLED", False),
        cache_dir=os.getenv("MM_CACHE_DIR", "/data/cache"),
        office_enabled=_bool_env("MULTIMODAL_OFFICE_ENABLED", False),
        allowed_suffixes=allowed or None,
        parser_timeout=float(os.getenv("MM_PARSER_TIMEOUT", "15")),
    )


def _prepare_chunks_for_chroma(
    chunks: Iterable[Chunk],
    base_metadata: Dict[str, str],
) -> tuple[list[str], list[str], list[Dict[str, MetadataValue]], Dict[str, int]]:
    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[Dict[str, MetadataValue]] = []
    modalities = Counter({"text": 0, "image": 0, "table": 0, "formula": 0, "other": 0})
    seen: set[str] = set()
    for chunk in chunks:
        text = (chunk.text or "").strip()
        if not text:
            continue
        chunk_id = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if chunk_id in seen:
            continue
        seen.add(chunk_id)
        modalities[chunk.modality] += 1
        ids.append(chunk_id)
        documents.append(text)
        meta = {**base_metadata, **chunk.meta, "modality": chunk.modality, "sha256": chunk_id}
        metadatas.append(normalize_metadata(meta))
    return ids, documents, metadatas, dict(modalities)


def _upsert_into_chroma(
    ids: list[str],
    documents: list[str],
    metadatas: list[Dict[str, MetadataValue]],
) -> tuple[int, int]:
    if not ids:
        return 0, 0
    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    existing = collection.get(ids=ids)
    existing_ids = set(existing.get("ids", []))
    to_add_idx = [i for i, cid in enumerate(ids) if cid not in existing_ids]
    if not to_add_idx:
        return 0, len(ids)
    embedder = OllamaEmbeddings(model=EMBED_MODEL, base_url=OLLAMA_URL)
    docs_to_add = [documents[i] for i in to_add_idx]
    ids_to_add = [ids[i] for i in to_add_idx]
    metas_to_add = [metadatas[i] for i in to_add_idx]
    embeddings_raw = embedder.embed_documents(docs_to_add)
    embeddings_processed = [[float(value) for value in vector] for vector in embeddings_raw]
    typed_metas = cast(list[Mapping[str, MetadataValue]], metas_to_add)
    typed_embeddings = cast(list[Sequence[float]], embeddings_processed)
    collection.add(
        documents=docs_to_add,
        ids=ids_to_add,
        metadatas=typed_metas,
        embeddings=typed_embeddings,
    )
    return len(ids_to_add), len(ids) - len(ids_to_add)


def _text_chunks_from_path(path: Path) -> Iterable[Chunk]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        docs = PyPDFLoader(str(path)).load()
    elif suffix in {".doc", ".docx"}:
        docs = load_docx(str(path))
    else:
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(errors="ignore")
        docs = [Document(page_content=text, metadata={"source": path.name})]
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    for doc in splitter.split_documents(docs):
        text = (doc.page_content or "").strip()
        if not text:
            continue
        meta = dict(doc.metadata or {})
        meta.setdefault("parser", "text")
        meta.setdefault("source_path", path.name)
        meta.setdefault("source", path.name)
        meta.setdefault("source_tmp_path", str(path))
        yield Chunk(text=text[:8000], modality="text", meta=meta)


def load_docx(file_path: str) -> list[Document]:
    try:
        document = docx.Document(file_path)
    except Exception as exc:  # pragma: no cover - I/O guard
        raise HTTPException(status_code=400, detail=f"Impossible de lire le DOCX: {exc}")
    texts = [p.text.strip() for p in document.paragraphs if p.text and p.text.strip()]
    if not texts:
        return []
    joined = "\n".join(texts)
    return [Document(page_content=joined, metadata={"source": Path(file_path).name})]


def _resolve_local_path(raw_path: str) -> Path:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = (LOCAL_SOURCE_ROOT / candidate).resolve()
    else:
        candidate = candidate.resolve()
    if not ALLOW_UNRESTRICTED_LOCAL and not str(candidate).startswith(str(LOCAL_SOURCE_ROOT)):
        raise HTTPException(status_code=400, detail="Chemin local en dehors de la zone autorisée")
    if not candidate.exists():
        raise HTTPException(status_code=400, detail="Fichier introuvable")
    if not candidate.is_file():
        raise HTTPException(status_code=400, detail="Le chemin indiqué n'est pas un fichier")
    return candidate


def _validate_remote_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme.lower() not in URL_SCHEMES_ALLOWED:
        raise HTTPException(status_code=400, detail="Schéma d'URL non autorisé")
    if not parsed.hostname:
        raise HTTPException(status_code=400, detail="URL invalide")
    try:
        addr_info = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise HTTPException(status_code=400, detail=f"Résolution DNS impossible: {exc}")
    for entry in addr_info:
        address = ipaddress.ip_address(entry[4][0])
        if address.is_private or address.is_loopback or address.is_link_local or address.is_multicast or address.is_reserved:
            raise HTTPException(status_code=400, detail="URL interne non autorisée")


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
                        raise HTTPException(status_code=400, detail="Fichier distant trop volumineux")
                    tmp_file.write(chunk)
                return Path(tmp_file.name)
    except HTTPException:
        raise
    except requests.RequestException as exc:
        raise HTTPException(status_code=400, detail=f"Téléchargement impossible: {exc}")


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
                raise HTTPException(status_code=400, detail="Réponse distante trop volumineuse")
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_REMOTE_BYTES:
                    raise HTTPException(status_code=400, detail="Réponse distante trop volumineuse")
                chunks.append(chunk)
            encoding = response.encoding or "utf-8"
            text = b"".join(chunks).decode(encoding, errors="ignore")
            if not text.strip():
                raise HTTPException(status_code=400, detail="Aucun contenu exploitable sur la page")
            return response.url, text
    except HTTPException:
        raise
    except requests.RequestException as exc:
        raise HTTPException(status_code=400, detail=f"Téléchargement impossible: {exc}")


def load_from_url(url: str) -> list[Document]:
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
    text_only = soup.get_text("\n", strip=True)
    if not text_only:
        raise HTTPException(status_code=400, detail="Aucun contenu exploitable sur la page")
    return [Document(page_content=text_only, metadata={"source": final_url})]


@app.post("/ingest")
async def ingest_file(
    request: Request,
    file: UploadFile = File(...),
    mode: str = Query("text"),
    x_api_token: str | None = Header(default=None, convert_underscores=False),
) -> Dict[str, object]:
    _enforce_security(request, x_api_token)
    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_UPLOAD_MIME:
        raise HTTPException(status_code=415, detail="Unsupported media type")
    max_mb = int(os.getenv("INGEST_MAX_FILE_MB", "20"))
    tmp_path, total_bytes = await _persist_upload(file, max_mb)
    parse_mode = _parse_mode(request, mode)
    source_name = file.filename or tmp_path.name
    base_metadata = {
        "source": source_name,
        "source_name": source_name,
        "source_tmp_path": str(tmp_path),
        "ingest_mode": parse_mode,
        "ingest_ts": _current_timestamp(),
    }
    try:
        if parse_mode == "multimodal" and _multimodal_enabled():
            cfg = _build_mm_config()
            chunks = list(yield_chunks_from_path(tmp_path, cfg))
            ids, docs, metas, modalities = _prepare_chunks_for_chroma(chunks, base_metadata)
            added, skipped = _upsert_into_chroma(ids, docs, metas)
            LOGGER.info(
                {
                    "event": "ingest_multimodal",
                    "file": file.filename,
                    "added": added,
                    "skipped": skipped,
                    "modalities": modalities,
                    "bytes": total_bytes,
                }
            )
            response = IngestResponse(status="ok", added=added, skipped=skipped, modalities=modalities)
            return response.model_dump()
        chunks = list(_text_chunks_from_path(tmp_path))
        ids, docs, metas, modalities = _prepare_chunks_for_chroma(chunks, base_metadata)
        added, skipped = _upsert_into_chroma(ids, docs, metas)
        LOGGER.info(
            {
                "event": "ingest_text",
                "file": file.filename,
                "added": added,
                "skipped": skipped,
                "modalities": modalities,
                "bytes": total_bytes,
            }
        )
        response = IngestResponse(status="ok", added=added, skipped=skipped, modalities=modalities)
        return response.model_dump()
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


@app.post("/ingest/source")
def ingest_from_descriptor(
    request: Request,
    payload: IngestRequest,
    x_api_token: str | None = Header(default=None, convert_underscores=False),
) -> Dict[str, object]:
    _enforce_security(request, x_api_token)
    try:
        if payload.source_type == "url":
            docs = load_from_url(payload.source)
        elif payload.source_type == "gdrive_folder":
            loader = GoogleDriveLoader(folder_id=payload.source, recursive=True)
            docs = loader.load()
        elif payload.source_type == "pdf":
            path = _resolve_local_path(payload.source)
            docs = PyPDFLoader(str(path)).load()
        elif payload.source_type == "docx":
            path = _resolve_local_path(payload.source)
            docs = load_docx(str(path))
        else:
            raise HTTPException(status_code=400, detail=f"source_type non géré: {payload.source_type}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Erreur de chargement: {exc}")
    if not docs:
        return {"status": "ok", "added": 0, "skipped": 0, "modalities": {}}
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    chunk_objs: list[Chunk] = []
    for doc in splitter.split_documents(docs):
        text = (doc.page_content or "").strip()
        if not text:
            continue
        meta = {**(doc.metadata or {}), **payload.metadata_hints}
        meta.update({"source": payload.source, "source_type": payload.source_type, "parser": "text"})
        chunk_objs.append(Chunk(text=text[:8000], modality="text", meta=meta))
    base = {
        "ingest_mode": "json",
        "ingest_ts": _current_timestamp(),
        "source": payload.source,
        "source_name": payload.source,
    }
    ids, docs_txt, metas, modalities = _prepare_chunks_for_chroma(chunk_objs, base)
    added, skipped = _upsert_into_chroma(ids, docs_txt, metas)
    LOGGER.info(
        {
            "event": "ingest_descriptor",
            "source": payload.source,
            "added": added,
            "skipped": skipped,
            "modalities": modalities,
        }
    )
    response = IngestResponse(status="ok", added=added, skipped=skipped, modalities=modalities)
    return response.model_dump()


@app.get("/health")
def health_check() -> Dict[str, str]:
    return {"status": "healthy"}
