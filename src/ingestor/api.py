# pylint: disable=missing-module-docstring,missing-class-docstring,missing-function-docstring,line-too-long,too-many-locals,too-many-branches,too-many-statements,wrong-import-position
# cspell:ignore chromadb docx bs4 fastapi langchain gdrive nomic sha256 ollama allowlist metadatas CIDR
# File: /srv/rag/ingestor/api.py
from __future__ import annotations

import hashlib
import hmac
import importlib
import ipaddress
import logging
import os
import socket
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal, Optional, Protocol
from urllib.parse import urlparse

import requests

if TYPE_CHECKING:
    class ChromaCollectionProtocol(Protocol):
        def get(self, *, ids: Sequence[str]) -> Mapping[str, Sequence[Any]]: ...

        def add(
            self,
            *,
            documents: Sequence[str],
            ids: Sequence[str],
            metadatas: Sequence[Mapping[str, Any]],
            embeddings: Sequence[Sequence[float]],
        ) -> None: ...

    class ChromaHttpClient(Protocol):
        def get_or_create_collection(
            self,
            name: str,
            metadata: Mapping[str, Any] | None = None,
        ) -> ChromaCollectionProtocol: ...
else:  # pragma: no cover - runtime fallback for optional deps
    ChromaCollectionProtocol = Any
    ChromaHttpClient = Any

try:
    from fastapi import FastAPI, Header, HTTPException, Request, status
except ImportError as exc:  # pragma: no cover - fail fast with guidance
    raise RuntimeError(
        "Required module 'fastapi' is missing for the ingestion service. "
        "Install dependencies with `pip install -r src/ingestor/requirements.txt`."
    ) from exc
from pydantic import BaseModel, ConfigDict, Field


def _require_module(module_path: str, friendly_name: str):
    try:
        return importlib.import_module(module_path)
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            f"Required module '{friendly_name}' is missing for the ingestion service. "
            "Install dependencies with `pip install -r src/ingestor/requirements.txt`."
        ) from exc


chromadb = _require_module("chromadb", "chromadb")
docx = _require_module("docx", "python-docx")
bs4_module = _require_module("bs4", "beautifulsoup4")
BeautifulSoup = bs4_module.BeautifulSoup

doc_loaders_module = _require_module("langchain_community.document_loaders", "langchain-community")
PyPDFLoader = doc_loaders_module.PyPDFLoader

embeddings_module = _require_module("langchain_community.embeddings", "langchain-community")
OllamaEmbeddings = embeddings_module.OllamaEmbeddings

documents_module = _require_module("langchain_core.documents", "langchain-core")
Document = documents_module.Document

google_module = _require_module("langchain_google_community", "langchain-google-community")
GoogleDriveLoader = google_module.GoogleDriveLoader

splitters_module = _require_module("langchain_text_splitters", "langchain-text-splitters")
RecursiveCharacterTextSplitter = splitters_module.RecursiveCharacterTextSplitter


# --- Configuration ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
COLLECTION_NAME = "ressources_pedagogiques_terminale"
MAX_REMOTE_BYTES = int(os.getenv("MAX_REMOTE_BYTES", str(10 * 1024 * 1024)))
LOCAL_SOURCE_ROOT = Path(os.getenv("LOCAL_SOURCE_ROOT", "/data/uploads")).resolve()
ALLOW_UNRESTRICTED_LOCAL = os.getenv("ALLOW_UNRESTRICTED_LOCAL", "false").lower() == "true"
URL_SCHEMES_ALLOWED = {"http", "https"}
API_TOKEN = os.getenv("INGESTOR_API_TOKEN") or os.getenv("INGEST_AUTH_TOKEN")
API_TOKEN_HEADER = os.getenv(
    "INGESTOR_TOKEN_HEADER",
    os.getenv("INGEST_AUTH_HEADER", "X-API-Token"),
)
IP_ALLOWLIST = [
    entry.strip()
    for entry in os.getenv("INGESTOR_IP_ALLOWLIST", "").split(",")
    if entry.strip()
]
USER_AGENT = os.getenv(
    "USER_AGENT",
    os.getenv(
        "INGEST_REQUEST_UA",
        "rag-local-ingestor/1.0 (+https://github.com/cyranoaladin/rag-local)",
    ),
)
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "15"))

logger = logging.getLogger("ingestor")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

TOKEN_HEADER_CANDIDATES = [header for header in (API_TOKEN_HEADER or "",) if header]
for fallback in ("X-API-Token", "X-INGEST-TOKEN"):
    if fallback not in TOKEN_HEADER_CANDIDATES:
        TOKEN_HEADER_CANDIDATES.append(fallback)

IP_ALLOWLIST_NETWORKS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
for cidr in IP_ALLOWLIST:
    try:
        IP_ALLOWLIST_NETWORKS.append(ipaddress.ip_network(cidr, strict=False))
    except ValueError:
        logger.warning("CIDR ignored in INGESTOR_IP_ALLOWLIST: %s", cidr)

app = FastAPI(title="RAG Ingestor API")

# --- Request model ---


class IngestRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    source_type: Literal["url", "gdrive_folder", "pdf", "docx"]
    source: str
    metadata_hints: dict[str, str] = Field(default_factory=dict, alias="hints")

# --- Utilities ---


def normalize_metadata(d: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(k).strip().lower().replace(" ", "_"): v
        for k, v in d.items()
        if v not in (None, "")
    }


def get_content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _resolve_local_path(raw_path: str) -> Path:
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = (LOCAL_SOURCE_ROOT / candidate).resolve()
    else:
        candidate = candidate.resolve()
    if not ALLOW_UNRESTRICTED_LOCAL and not str(candidate).startswith(str(LOCAL_SOURCE_ROOT)):
        raise HTTPException(status_code=400, detail="Local path is outside the allowed area")
    if not candidate.exists():
        raise HTTPException(status_code=400, detail="File not found")
    if not candidate.is_file():
        raise HTTPException(status_code=400, detail="Path is not a file")
    return candidate


def load_docx(file_path: str):
    try:
        d = docx.Document(file_path)
    except Exception as e:  # pragma: no cover
        raise HTTPException(status_code=400, detail=f"DOCX read failed: {e}") from e
    texts = []
    for p in d.paragraphs:
        if p.text and p.text.strip():
            texts.append(p.text.strip())
    # simple extraction; tables could be added later if needed
    content = "\n".join(texts).strip()
    if not content:
        return []
    return [Document(page_content=content, metadata={"source": os.path.basename(file_path)})]


def _validate_remote_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme.lower() not in URL_SCHEMES_ALLOWED:
        raise HTTPException(status_code=400, detail="URL scheme not allowed")
    if not parsed.hostname:
        raise HTTPException(status_code=400, detail="Invalid URL")
    try:
        socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise HTTPException(status_code=400, detail=f"DNS resolution failed: {exc}") from exc
    for entry in socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)):
        ip = ipaddress.ip_address(entry[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            raise HTTPException(status_code=400, detail="Private/internal URL not allowed")


def _download_to_temp(url: str, suffix: str) -> Path:
    _validate_remote_url(url)
    try:
        with requests.get(
            url,
            timeout=HTTP_TIMEOUT,
            stream=True,
            headers={"User-Agent": USER_AGENT},
        ) as response:
            response.raise_for_status()
            total = 0
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp_file:
                for chunk in response.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_REMOTE_BYTES:
                        raise HTTPException(status_code=400, detail="Remote file too large")
                    tmp_file.write(chunk)
                return Path(tmp_file.name)
    except requests.RequestException as exc:
        raise HTTPException(status_code=400, detail=f"Download failed: {exc}") from exc


def _fetch_remote_text(url: str) -> tuple[str, str]:
    _validate_remote_url(url)
    try:
        with requests.get(
            url,
            timeout=HTTP_TIMEOUT,
            allow_redirects=True,
            stream=True,
            headers={"User-Agent": USER_AGENT},
        ) as response:
            if response.history:
                for hop in response.history:
                    _validate_remote_url(hop.url)
            _validate_remote_url(response.url)
            declared_length = response.headers.get("content-length")
            if declared_length and int(declared_length) > MAX_REMOTE_BYTES:
                raise HTTPException(status_code=400, detail="Remote response too large")
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_REMOTE_BYTES:
                    raise HTTPException(status_code=400, detail="Remote response too large")
                chunks.append(chunk)
            encoding = response.encoding or "utf-8"
            text = b"".join(chunks).decode(encoding, errors="ignore")
            if not text.strip():
                raise HTTPException(status_code=400, detail="No usable content on the page")
            return response.url, text
    except requests.RequestException as exc:
        raise HTTPException(status_code=400, detail=f"Download failed: {exc}") from exc


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
        raise HTTPException(status_code=400, detail="No usable content on the page")
    return [Document(page_content=text, metadata={"source": final_url})]

# --- Chroma client factory ---


def get_chroma_client() -> ChromaHttpClient:
    return chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)

# --- Endpoint helpers ---


def _client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if forwarded_for:
        return forwarded_for
    return request.client.host if request.client else ""


def _enforce_token(request: Request, provided_header: str | None) -> None:
    if not API_TOKEN:
        return
    candidate = provided_header
    if not candidate:
        for header_name in TOKEN_HEADER_CANDIDATES:
            value = request.headers.get(header_name)
            if value:
                candidate = value
                break
    if not candidate or not hmac.compare_digest(candidate, API_TOKEN):
        client_ip = _client_ip(request) or "unknown"
        logger.warning("unauthorized: bad token from %s", client_ip)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


def _enforce_ip_allowlist(request: Request) -> None:
    if not IP_ALLOWLIST_NETWORKS:
        return
    client_ip = _client_ip(request)
    try:
        ip_obj = ipaddress.ip_address(client_ip)
    except ValueError:
        logger.warning("forbidden: invalid client IP '%s'", client_ip)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden") from None
    if not any(ip_obj in network for network in IP_ALLOWLIST_NETWORKS):
        logger.warning("forbidden: ip %s not in allowlist", client_ip)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


@app.post("/ingest")
def ingest_data(
    req: IngestRequest,
    request: Request,
    x_api_token: Annotated[Optional[str], Header(alias="X-API-Token")] = None,  # noqa: UP007,UP045 - Optional keeps py39 happy
):
    # 1) Load & access controls
    _enforce_token(request, x_api_token)
    _enforce_ip_allowlist(request)
    try:
        if req.source_type == "url":
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
            raise HTTPException(status_code=400, detail=f"Unsupported source_type: {req.source_type}")
    except HTTPException:
        raise
    except Exception as e:  # pragma: no cover
        logger.exception(
            "Unexpected error while loading source '%s' (%s)",
            req.source,
            req.source_type,
        )
        raise HTTPException(status_code=500, detail=f"Load error: {e}") from e

    if not docs:
        return {"status": "ok", "message": "No document loaded."}

    # 2) Split
    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
    chunks = splitter.split_documents(docs)
    if not chunks:
        return {"status": "ok", "message": "No textual chunk after splitting."}

    # 3) Prepare
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
        merged.update(req.metadata_hints)
        ids.append(content_hash)
        documents.append(text)
        metadatas.append(normalize_metadata(merged))

    if not ids:
        return {"status": "ok", "message": "No eligible content to ingest."}

    # 4) Insert (with de-duplication by hash)
    try:
        client = get_chroma_client()
        collection = client.get_or_create_collection(name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"})

        existing = collection.get(ids=ids)
        # already-existing ids
        existing_ids = set(existing.get("ids", []))

        to_add_idx = [i for i, _id in enumerate(ids) if _id not in existing_ids]
        if not to_add_idx:
            return {"status": "ok", "added": 0, "skipped": len(ids)}

        emb = OllamaEmbeddings(model=EMBED_MODEL, base_url=OLLAMA_URL)
        docs_to_add = [documents[i] for i in to_add_idx]
        ids_to_add = [ids[i] for i in to_add_idx]
        meta_to_add = [metadatas[i] for i in to_add_idx]
        embs_to_add = emb.embed_documents(docs_to_add)

        collection.add(
            documents=docs_to_add,
            ids=ids_to_add,
            metadatas=meta_to_add,
            embeddings=embs_to_add,
        )
        added = len(ids_to_add)
        logger.info(
            "Ingestion finished: added=%s skipped(existing)=%s source=%s type=%s",
            added,
            len(existing_ids),
            req.source,
            req.source_type,
        )
        return {"status": "ok", "added": added, "skipped": len(existing_ids)}
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - logged for diagnostics
        logger.exception("embedding/indexing failed: %s", exc)
        raise HTTPException(status_code=502, detail="Embedding/Indexing failed") from exc


@app.get("/health")
def health_check():
    return {"status": "healthy"}
