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
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Annotated, Any, Literal, NamedTuple, Optional, Protocol
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

    class DocumentProtocol(Protocol):
        page_content: str | None
        metadata: Mapping[str, Any] | None
else:  # pragma: no cover - runtime fallback for optional deps
    ChromaCollectionProtocol = Any
    ChromaHttpClient = Any
    DocumentProtocol = Any

try:
    from fastapi import FastAPI, Header, HTTPException, Request, Response, status
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
METRICS_ENABLED = os.getenv("METRICS_ENABLED", "false").lower() == "true"
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
INGEST_CHUNK_SIZE = int(os.getenv("INGEST_CHUNK_SIZE", "800"))
INGEST_CHUNK_OVERLAP = int(os.getenv("INGEST_CHUNK_OVERLAP", "120"))

DEFAULT_MODALITY = "unknown"
MODALITY_FALLBACK: dict[str, str] = {
    "url": "text",
    "gdrive_folder": "document",
    "pdf": "pdf",
    "docx": "docx",
}

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

# --- Prometheus Metrics (optional) ---
PROMETHEUS_AVAILABLE = False
PROMETHEUS_REGISTRY: Any | None = None
_generate_latest: Callable[[Any], bytes] | None = None
_PROMETHEUS_CONTENT_TYPE: str | None = None
ingest_requests_total = None
ingest_duration_seconds = None

if METRICS_ENABLED:
    try:
        from prometheus_client import (
            CONTENT_TYPE_LATEST,
            CollectorRegistry,
            Counter,
            Histogram,
            generate_latest,
        )

        PROMETHEUS_REGISTRY = CollectorRegistry()
        ingest_requests_total = Counter(
            "ingestor_ingests_total",
            "Total ingestion requests processed",
            ["source", "modality", "status"],
            registry=PROMETHEUS_REGISTRY,
        )
        ingest_duration_seconds = Histogram(
            "ingestor_ingest_duration_seconds",
            "Time spent processing ingestion requests",
            ["source", "modality"],
            buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0, float("inf")),
            registry=PROMETHEUS_REGISTRY,
        )
        _generate_latest = generate_latest
        _PROMETHEUS_CONTENT_TYPE = CONTENT_TYPE_LATEST
        PROMETHEUS_AVAILABLE = True
        logger.info("Prometheus metrics enabled")
    except ImportError:  # pragma: no cover
        logger.warning("prometheus_client not available, metrics disabled")


class _NoopMetricsRecorder:
    __slots__ = ()

    def set_modality(self, modality: str) -> None:  # pragma: no cover - trivial
        _ = modality

    def observe(self, status: str) -> None:  # pragma: no cover - trivial
        _ = status


class _IngestMetricsRecorder:
    __slots__ = ("_source", "_modality", "_start")

    def __init__(self, source_label: str):
        self._source = source_label or DEFAULT_MODALITY
        self._modality = DEFAULT_MODALITY
        self._start = perf_counter() if ingest_duration_seconds is not None else None

    def set_modality(self, modality_label: str) -> None:
        if modality_label:
            self._modality = modality_label

    def observe(self, status: str) -> None:
        if ingest_requests_total is not None:
            ingest_requests_total.labels(
                source=self._source,
                modality=self._modality,
                status=status,
            ).inc()
        if self._start is not None and ingest_duration_seconds is not None:
            duration = perf_counter() - self._start
            if duration < 0:
                duration = 0.0
            ingest_duration_seconds.labels(
                source=self._source,
                modality=self._modality,
            ).observe(duration)


def _metrics_recorder(source_label: str) -> _NoopMetricsRecorder | _IngestMetricsRecorder:
    if not PROMETHEUS_AVAILABLE or ingest_requests_total is None:
        return _NoopMetricsRecorder()
    return _IngestMetricsRecorder(source_label)

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


class PreparedChunks(NamedTuple):
    ids: list[str]
    documents: list[str]
    metadatas: list[dict[str, Any]]
    modality: str


def _resolve_modality(source_type: str, metadata: Mapping[str, Any] | None = None) -> str:
    if metadata:
        candidate = metadata.get("modality")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip().lower()
        for key in ("mime_type", "content_type", "file_extension"):
            value = metadata.get(key)
            if not isinstance(value, str):
                continue
            lowered = value.lower()
            if "pdf" in lowered:
                return "pdf"
            if "docx" in lowered or "word" in lowered:
                return "docx"
            if "html" in lowered or "text" in lowered:
                return "text"
    return MODALITY_FALLBACK.get(source_type, DEFAULT_MODALITY)


def _prepare_chunks_for_chroma(
    req: IngestRequest,
    documents: Sequence[DocumentProtocol],
    splitter: Any | None = None,
) -> PreparedChunks:
    if not documents:
        fallback_modality = MODALITY_FALLBACK.get(req.source_type, DEFAULT_MODALITY)
        return PreparedChunks([], [], [], fallback_modality)

    splitter_obj = splitter or RecursiveCharacterTextSplitter(
        chunk_size=INGEST_CHUNK_SIZE,
        chunk_overlap=INGEST_CHUNK_OVERLAP,
    )
    chunks = splitter_obj.split_documents(documents)

    ids: list[str] = []
    contents: list[str] = []
    metadatas: list[dict[str, Any]] = []
    aggregate_modality = MODALITY_FALLBACK.get(req.source_type, DEFAULT_MODALITY)

    for chunk in chunks:
        text = (chunk.page_content or "").strip()
        if not text:
            continue
        chunk_metadata = getattr(chunk, "metadata", {}) or {}
        chunk_modality = _resolve_modality(req.source_type, chunk_metadata)
        if aggregate_modality == DEFAULT_MODALITY and chunk_modality != DEFAULT_MODALITY:
            aggregate_modality = chunk_modality
        content_hash = get_content_hash(text)
        merged_metadata: dict[str, Any] = {
            "sha256": content_hash,
            "source_type": req.source_type,
            "source": req.source,
            "modality": chunk_modality,
        }
        merged_metadata.update(chunk_metadata)
        merged_metadata.update(req.metadata_hints)
        ids.append(content_hash)
        contents.append(text)
        metadatas.append(normalize_metadata(merged_metadata))

    return PreparedChunks(ids, contents, metadatas, aggregate_modality)


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


def _enforce_security(request: Request, provided_header: str | None) -> None:
    _enforce_token(request, provided_header)
    _enforce_ip_allowlist(request)


@app.post("/ingest")
def ingest_data(
    req: IngestRequest,
    request: Request,
    x_api_token: Annotated[Optional[str], Header(alias="X-API-Token")] = None,  # noqa: UP007,UP045 - Optional keeps py39 happy
):
    recorder = _metrics_recorder(req.source_type)
    try:
        _enforce_security(request, x_api_token)
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
    except HTTPException as exc:
        recorder.observe(f"http_{exc.status_code}")
        raise
    except Exception as e:  # pragma: no cover
        logger.exception(
            "Unexpected error while loading source '%s' (%s)",
            req.source,
            req.source_type,
        )
        recorder.observe("error")
        raise HTTPException(status_code=500, detail=f"Load error: {e}") from e

    if not docs:
        recorder.observe("success")
        return {"status": "ok", "message": "No document loaded."}

    prepared = _prepare_chunks_for_chroma(req, docs)
    recorder.set_modality(prepared.modality)
    if not prepared.ids:
        recorder.observe("success")
        return {"status": "ok", "message": "No eligible content to ingest."}

    # 4) Insert (with de-duplication by hash)
    try:
        client = get_chroma_client()
        collection = client.get_or_create_collection(name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"})

        existing = collection.get(ids=prepared.ids)
        # already-existing ids
        existing_ids = set(existing.get("ids", []))

        to_add_idx = [i for i, chunk_id in enumerate(prepared.ids) if chunk_id not in existing_ids]
        if not to_add_idx:
            recorder.observe("success")
            return {"status": "ok", "added": 0, "skipped": len(prepared.ids)}

        emb = OllamaEmbeddings(model=EMBED_MODEL, base_url=OLLAMA_URL)
        docs_to_add = [prepared.documents[i] for i in to_add_idx]
        ids_to_add = [prepared.ids[i] for i in to_add_idx]
        meta_to_add = [prepared.metadatas[i] for i in to_add_idx]
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
        recorder.observe("success")
        return {"status": "ok", "added": added, "skipped": len(existing_ids)}
    except HTTPException as exc:
        recorder.observe(f"http_{exc.status_code}")
        raise
    except Exception as exc:  # pragma: no cover - logged for diagnostics
        logger.exception("embedding/indexing failed: %s", exc)
        recorder.observe("error")
        raise HTTPException(status_code=502, detail="Embedding/Indexing failed") from exc


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.get("/metrics")
def get_metrics():
    """Prometheus metrics endpoint (requires METRICS_ENABLED=true)"""
    if (
        not METRICS_ENABLED
        or not PROMETHEUS_AVAILABLE
        or _generate_latest is None
        or _PROMETHEUS_CONTENT_TYPE is None
        or PROMETHEUS_REGISTRY is None
    ):
        raise HTTPException(status_code=404, detail="Metrics not enabled")

    return Response(
        content=_generate_latest(PROMETHEUS_REGISTRY),
        media_type=_PROMETHEUS_CONTENT_TYPE,
    )
