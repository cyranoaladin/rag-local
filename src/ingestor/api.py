
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import ipaddress
import logging
import mimetypes
import os
import socket
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, Literal, cast
from urllib.parse import urlparse

import chromadb
import requests
from bs4 import BeautifulSoup
from chromadb.config import Settings
from fastapi import FastAPI, HTTPException, Query, Request, Response
from langchain.document_loaders import GoogleDriveLoader, PyPDFLoader
from langchain.embeddings.ollama import OllamaEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from prometheus_client import CONTENT_TYPE_LATEST
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from langchain.schema import Document
else:
    try:
        from langchain.schema import Document
    except ImportError:
        Document = Any  # fallback for type checking

# --- Metrics module loader ---
def _load_metrics_module() -> ModuleType:
    module_name = "src.ingestor.metrics"
    existing = sys.modules.get(module_name)
    if isinstance(existing, ModuleType):
        return existing
    spec = importlib.util.spec_from_file_location(
        module_name,
        Path(__file__).with_name("metrics.py"),
    )
    if spec and spec.loader:
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    raise ImportError("Unable to load metrics module")

ingest_metrics: ModuleType = _load_metrics_module()

# --- Configuration ---
CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000"))
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
COLLECTION_NAME = "ressources_pedagogiques_terminale"
CHROMA_REQUEST_TIMEOUT = float(os.getenv("CHROMA_REQUEST_TIMEOUT", "30"))
OLLAMA_REQUEST_TIMEOUT = float(os.getenv("OLLAMA_REQUEST_TIMEOUT", "30"))
MAX_REMOTE_BYTES = int(os.getenv("MAX_REMOTE_BYTES", str(10 * 1024 * 1024)))
LOCAL_SOURCE_ROOT = Path(
    os.getenv("LOCAL_SOURCE_ROOT", "/data/uploads")).resolve()
ALLOW_UNRESTRICTED_LOCAL = os.getenv(
    "ALLOW_UNRESTRICTED_LOCAL", "false").lower() == "true"
URL_SCHEMES_ALLOWED = {"http", "https"}

INGEST_CHUNK_SIZE = int(os.getenv("INGEST_CHUNK_SIZE", "1000"))
INGEST_CHUNK_OVERLAP = int(os.getenv("INGEST_CHUNK_OVERLAP", "150"))
METRICS_ENABLED = ingest_metrics.METRICS_ENABLED
MULTIMODAL_ENABLED = os.getenv("MULTIMODAL_ENABLED", "false").lower() == "true"
MM_PARSER_TIMEOUT = float(os.getenv("MM_PARSER_TIMEOUT", "30"))
MM_MAX_CHARS_PER_CHUNK = int(os.getenv("MM_MAX_CHARS_PER_CHUNK", "1200"))
MM_CACHE_DIR = os.getenv("MM_CACHE_DIR", "/data/mm-cache")
GOOGLE_DRIVE_TOKEN_PATH = os.getenv("GOOGLE_DRIVE_TOKEN_PATH", "/tmp/google-drive-token.json")

# Keep metrics isolated per module import to avoid duplicate registration in tests.
METRIC_REGISTRY = ingest_metrics.REGISTRY
REQUEST_COUNT = ingest_metrics.REQUEST_COUNT
REQUEST_LATENCY = ingest_metrics.REQUEST_LATENCY
INGEST_RESULT = ingest_metrics.INGEST_RESULT
ingest_requests_total = ingest_metrics.ingest_requests_total

logger = logging.getLogger(__name__)

try:
    from .mm_adapter import Chunk, parse_multimodal
except ImportError:
    # Allow running when the module is executed as a top-level script (e.g. inside Docker).
    from mm_adapter import Chunk, parse_multimodal  # type: ignore[no-redef]

try:
    from . import admin_api as _admin_api_module
except ImportError:  # pragma: no cover - Docker execution path
    _admin_api_module = importlib.import_module("admin_api")

admin_api = _admin_api_module


@dataclass
class PreparedBatch:
    ids: list[str]
    documents: list[str]
    metadatas: list[dict[str, str]]
    modality: str

app = FastAPI(title="RAG Ingestor API")
app.include_router(admin_api.router)


@app.middleware("http")
async def _metrics_middleware(request, call_next):
    start = time.perf_counter()
    code = 500
    try:
        response = await call_next(request)
        code = getattr(response, "status_code", 500)
    except Exception:
        code = 500
        raise
    finally:
        if ingest_metrics.METRICS_ENABLED:
            elapsed = time.perf_counter() - start
            path = request.url.path
            method = request.method
            REQUEST_LATENCY.labels(path=path, method=method).observe(elapsed)
            REQUEST_COUNT.labels(path=path, method=method, code=str(code)).inc()
    return response


def _record_ingest_metrics(ok: bool) -> None:
    if ingest_metrics.METRICS_ENABLED:
        INGEST_RESULT.labels(status="ok" if ok else "fail").inc()


def _record_ingest_outcome(source: str, modality: str, status: str) -> None:
    if not METRICS_ENABLED:
        return
    safe_source = (source or "unknown").strip().lower() or "unknown"
    safe_modality = (modality or "unknown").strip().lower() or "unknown"
    safe_status = (status or "unknown").strip().lower() or "unknown"
    ingest_requests_total.labels(
        source=safe_source, modality=safe_modality, status=safe_status
    ).inc()

# --- Modèle de requête ---


class IngestRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")
    source_type: Literal["url", "gdrive_folder", "pdf", "docx", "markdown", "md", "video"] = Field(
        alias="sourceType",
        validation_alias=AliasChoices("source_type", "sourceType"),
    )
    source: str = Field(
        alias="sourceUrl",
        validation_alias=AliasChoices("source", "sourceUrl"),
    )
    metadata_hints: dict[str, str] = Field(
        default_factory=dict,
        alias="metadata",
        validation_alias=AliasChoices("hints", "metadata"),
    )

# --- Utilitaires ---


def normalize_metadata(d: dict) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in d.items():
        if value in (None, ""):
            continue
        normalized[str(key).strip().lower().replace(" ", "_")] = str(value)
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


def _get_client_ip(request: Any) -> str:
    headers = getattr(request, "headers", {}) or {}
    forwarded = headers.get("X-Forwarded-For") or headers.get("x-forwarded-for")
    if isinstance(forwarded, str) and forwarded.strip():
        primary = forwarded.split(",")[0].strip()
        if primary:
            return primary
    client = getattr(request, "client", None)
    host = getattr(client, "host", None)
    if isinstance(host, str) and host:
        return host
    return "127.0.0.1"


def _ip_allowed(ip_str: str, allowlist: str | None) -> bool:
    if not allowlist:
        return True
    try:
        ip_obj = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    for cidr in allowlist.split(","):
        network = cidr.strip()
        if not network:
            continue
        try:
            if ip_obj in ipaddress.ip_network(network, strict=False):
                return True
        except ValueError:
            continue
    return False


def _enforce_security(request: Any, _req: Any) -> None:
    headers = getattr(request, "headers", {}) or {}
    token_env = os.getenv("INGESTOR_API_TOKEN") or os.getenv("INGEST_AUTH_TOKEN")
    if token_env:
        # Try X-API-Token first, then Authorization (Bearer or raw)
        header_token = headers.get("X-API-Token") or headers.get("x-api-token")
        if not header_token:
            auth = headers.get("Authorization") or headers.get("authorization")
            if isinstance(auth, str) and auth.strip():
                value = auth.strip()
                if value.lower().startswith("bearer "):
                    header_token = value.split(" ", 1)[1].strip()
                else:
                    header_token = value
        if header_token != token_env:
            raise HTTPException(status_code=401, detail="Unauthorized")

    allowlist = os.getenv("INGESTOR_IP_ALLOWLIST")
    if allowlist and not _ip_allowed(_get_client_ip(request), allowlist):
        raise HTTPException(status_code=403, detail="Forbidden")


def get_chroma_client() -> Any:
    timeout_seconds = max(1, int(CHROMA_REQUEST_TIMEOUT))
    settings = Settings(
        chroma_server_host=CHROMA_HOST,
        chroma_server_http_port=CHROMA_PORT,
        anonymized_telemetry=False,
        chroma_logservice_request_timeout_seconds=timeout_seconds,
        chroma_sysdb_request_timeout_seconds=timeout_seconds,
        chroma_query_request_timeout_seconds=timeout_seconds,
    )
    return chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT, settings=settings)


def _load_docx_basic(file_path: str) -> list[Document]:
    import docx
    try:
        d = docx.Document(file_path)
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Impossible de lire le DOCX: {e}") from e
    texts = []
    for p in d.paragraphs:
        if p.text and p.text.strip():
            texts.append(p.text.strip())
    # (option simple; on pourra enrichir avec les tableaux si besoin)
    content = "\n".join(texts).strip()
    if not content:
        return []
    return [Document(page_content=content, metadata={"source": os.path.basename(file_path)})]


def load_docx(file_path: str) -> list[Document]:
    try:
        from unstructured.partition.docx import partition_docx
    except ImportError:  # pragma: no cover - fallback when optional deps missing
        return _load_docx_basic(file_path)

    try:
        elements = partition_docx(filename=file_path, include_metadata=True)
    except Exception:
        logger.warning("partition_docx failed, falling back to basic DOCX loader", exc_info=True)
        return _load_docx_basic(file_path)

    documents: list[Document] = []
    for element in elements:
        text = getattr(element, "text", "") or ""
        text = text.strip()
        if not text:
            continue
        metadata_dict: dict[str, Any] = {}
        metadata_obj = getattr(element, "metadata", None)
        if metadata_obj is not None:
            try:
                raw_meta = metadata_obj.to_dict()
            except AttributeError:
                raw_meta = dict(metadata_obj) if isinstance(metadata_obj, dict) else {}
            for key, value in (raw_meta or {}).items():
                if value in (None, "", [], {}):
                    continue
                metadata_dict[str(key)] = str(value)
        metadata_dict.setdefault("source", os.path.basename(file_path))
        metadata_dict.setdefault(
            "mime_type",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        documents.append(Document(page_content=text, metadata=metadata_dict))

    if not documents:
        return _load_docx_basic(file_path)
    return documents


class TimedOllamaEmbeddings(OllamaEmbeddings):
    """Ollama embeddings client with explicit network timeout."""

    request_timeout: float = OLLAMA_REQUEST_TIMEOUT

    def _process_emb_response(self, input: str) -> list[float]:
        headers = {
            "Content-Type": "application/json",
            **(self.headers or {}),
        }

        try:
            res = requests.post(
                f"{self.base_url}/api/embeddings",
                headers=headers,
                json={"model": self.model, "prompt": input, **self._default_params},
                timeout=self.request_timeout,
            )
        except requests.exceptions.RequestException as e:
            raise ValueError(f"Error raised by inference endpoint: {e}") from e

        if res.status_code != 200:
            raise ValueError(
                f"Error raised by inference API HTTP code: {res.status_code}, {res.text}"
            )
        try:
            t = res.json()
            return t["embedding"]
        except requests.exceptions.JSONDecodeError as e:
            raise ValueError(
                f"Error raised by inference API: {e}.\nResponse: {res.text}"
            ) from e


def load_markdown(file_path: Path) -> list[Document]:
    try:
        raw_text = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raw_text = file_path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Impossible de lire le fichier Markdown: {exc}") from exc

    text = raw_text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Fichier Markdown vide")

    metadata = {"source": str(file_path), "mime_type": "text/markdown"}
    return [Document(page_content=text, metadata=metadata)]


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
            status_code=400, detail=f"Résolution DNS impossible: {exc}") from exc
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
            status_code=400, detail=f"Téléchargement impossible: {exc}") from exc


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
            status_code=400, detail=f"Téléchargement impossible: {exc}") from exc


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


def _load_source_documents(req: IngestRequest) -> list[Document]:
    if req.source_type == "url":
        return load_from_url(req.source)
    if req.source_type == "gdrive_folder":
        loader_kwargs: dict[str, Any] = {"folder_id": req.source, "recursive": True}
        service_account_raw = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if service_account_raw:
            service_account_path = Path(service_account_raw)
            if not service_account_path.exists():
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Configuration Google Drive invalide: le fichier de clé de service "
                        "spécifié par GOOGLE_APPLICATION_CREDENTIALS est introuvable."
                    ),
                )
            loader_kwargs["service_account_key"] = service_account_path
            loader_kwargs["credentials_path"] = service_account_path
        else:
            default_credentials = Path.home() / ".credentials" / "credentials.json"
            if default_credentials.exists():
                loader_kwargs["credentials_path"] = default_credentials
            else:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Identification Google Drive manquante: définissez GOOGLE_APPLICATION_CREDENTIALS "
                        "ou placez un credentials.json valide dans ~/.credentials/."
                    ),
                )

        token_path = Path(GOOGLE_DRIVE_TOKEN_PATH)
        try:
            token_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:  # pragma: no cover - defensive guard
            raise HTTPException(
                status_code=500,
                detail=f"Impossible de préparer le répertoire du token Google Drive: {exc}",
            ) from exc
        loader_kwargs["token_path"] = token_path

        try:
            loader = GoogleDriveLoader(**loader_kwargs)
        except ValueError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Configuration Google Drive invalide: {exc}",
            ) from exc
        return loader.load()
    if req.source_type == "pdf":
        path = _resolve_local_path(req.source)
        return PyPDFLoader(str(path)).load()
    if req.source_type == "docx":
        path = _resolve_local_path(req.source)
        return load_docx(str(path))
    if req.source_type in {"markdown", "md"}:
        path = _resolve_local_path(req.source)
        return load_markdown(path)
    if req.source_type == "video":
        raise HTTPException(
            status_code=400,
            detail="Ingestion vidéo disponible uniquement en mode multimodal (mode=multimodal).",
        )
    raise HTTPException(status_code=400, detail=f"source_type non géré: {req.source_type}")


def _prepare_chunks_for_chroma(
    req: IngestRequest,
    docs: list[Document],
    splitter: RecursiveCharacterTextSplitter | None = None,
) -> PreparedBatch:
    splitter = splitter or RecursiveCharacterTextSplitter(
        chunk_size=INGEST_CHUNK_SIZE, chunk_overlap=INGEST_CHUNK_OVERLAP
    )
    chunks = splitter.split_documents(docs)
    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict[str, str]] = []
    modality = "text"
    seen_ids: set[str] = set()

    for chunk in chunks:
        text = (chunk.page_content or "").strip()
        if not text:
            continue
        content_hash = get_content_hash(text)
        if content_hash in seen_ids:
            continue
        seen_ids.add(content_hash)
        chunk_modality = (chunk.metadata or {}).get("modality", "text")
        metadata = {
            "sha256": content_hash,
            "source_type": req.source_type,
            "source": req.source,
            "modality": chunk_modality,
        }
        metadata.update(chunk.metadata or {})
        metadata.update(req.metadata_hints or {})
        normalized = normalize_metadata(metadata)

        ids.append(content_hash)
        documents.append(text)
        metadatas.append(normalized)
        modality = normalized.get("modality", modality)

    if not ids:
        modality = "text"
    return PreparedBatch(ids=ids, documents=documents, metadatas=metadatas, modality=modality)


def _prepare_multimodal_chunks(req: IngestRequest, chunks: list[Chunk]) -> PreparedBatch:
    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict[str, str]] = []
    modality_counts: dict[str, int] = {}
    seen_ids: set[str] = set()

    for chunk in chunks:
        text = chunk.as_text() if hasattr(chunk, "as_text") else (chunk.text or "")
        text = (text or "").strip()
        if not text:
            continue
        content_hash = get_content_hash(text)
        if content_hash in seen_ids:
            continue
        seen_ids.add(content_hash)
        chunk_modality = (chunk.modality or "unknown").strip().lower() or "unknown"
        metadata: dict[str, Any] = {
            "sha256": content_hash,
            "source": req.source,
            "source_type": req.source_type,
            "modality": chunk_modality,
        }
        metadata.update(getattr(chunk, "metadata", {}) or {})
        metadata.update(req.metadata_hints or {})
        normalized = normalize_metadata(metadata)

        ids.append(content_hash)
        documents.append(text)
        metadatas.append(normalized)

        key = normalized.get("modality", chunk_modality)
        modality_counts[key] = modality_counts.get(key, 0) + 1

    if modality_counts:
        dominant = max(modality_counts.items(), key=lambda item: item[1])[0]
    else:
        dominant = "unknown"
    return PreparedBatch(ids=ids, documents=documents, metadatas=metadatas, modality=dominant)


def _prepare_multimodal_ingest(req: IngestRequest) -> PreparedBatch:
    if not MULTIMODAL_ENABLED:
        raise HTTPException(status_code=400, detail="Multimodal ingest disabled")
    path = _resolve_local_path(req.source)
    mime, _ = mimetypes.guess_type(path.name)
    with path.open("rb") as handle:
        chunk_iter = parse_multimodal(
            handle,
            filename=path.name,
            mime=mime or "application/octet-stream",
            timeout_s=MM_PARSER_TIMEOUT,
            max_chars_per_chunk=MM_MAX_CHARS_PER_CHUNK,
            cache_dir=MM_CACHE_DIR,
        )
        chunk_list = list(chunk_iter)
    return _prepare_multimodal_chunks(req, chunk_list)

# --- Endpoint ---


@app.post("/ingest")
def ingest_data(
    req: IngestRequest,
    request: Request,
    mode: str = Query(default="text"),
):
    modality_label = "unknown"
    mode_normalized = (mode or "text").strip().lower() or "text"

    try:
        _enforce_security(request, req)
    except HTTPException as exc:
        _record_ingest_outcome(req.source_type, modality_label, f"http_{exc.status_code}")
        raise

    try:
        if mode_normalized == "multimodal":
            prepared = _prepare_multimodal_ingest(req)
        elif mode_normalized in {"", "text"}:
            docs = _load_source_documents(req)
            if not docs:
                _record_ingest_metrics(True)
                modality_label = "text"
                _record_ingest_outcome(req.source_type, modality_label, "empty")
                return {"status": "ok", "message": "Aucun document chargé."}
            prepared = _prepare_chunks_for_chroma(req, docs)
        else:
            raise HTTPException(status_code=400, detail="Mode d'ingestion non supporté")
        modality_label = prepared.modality or "unknown"
    except HTTPException as exc:
        _record_ingest_metrics(False)
        _record_ingest_outcome(req.source_type, modality_label, f"http_{exc.status_code}")
        raise
    except Exception as exc:
        _record_ingest_metrics(False)
        _record_ingest_outcome(req.source_type, modality_label, "error")
        raise HTTPException(status_code=500, detail=f"Erreur de chargement: {exc}") from exc

    if not prepared.ids:
        _record_ingest_metrics(True)
        _record_ingest_outcome(req.source_type, modality_label, "empty")
        return {"status": "ok", "message": "Aucun contenu éligible à l'ingestion."}

    try:
        client = get_chroma_client()
        collection = client.get_or_create_collection(
            name=COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
        )

        existing = collection.get(ids=prepared.ids) or {}
        existing_ids = set(existing.get("ids", []))

        to_add_idx = [i for i, chunk_id in enumerate(prepared.ids) if chunk_id not in existing_ids]
        if not to_add_idx:
            _record_ingest_metrics(True)
            _record_ingest_outcome(req.source_type, modality_label, "skipped")
            return {"status": "ok", "added": 0, "skipped": len(prepared.ids)}

        emb = TimedOllamaEmbeddings(model=EMBED_MODEL, base_url=OLLAMA_URL, request_timeout=OLLAMA_REQUEST_TIMEOUT)
        docs_to_add = [prepared.documents[i] for i in to_add_idx]
        ids_to_add = [prepared.ids[i] for i in to_add_idx]
        meta_to_add = [prepared.metadatas[i] for i in to_add_idx]
        try:
            embs_to_add = emb.embed_documents(docs_to_add)
        except ValueError as exc:
            message = str(exc)
            if "HTTP code: 404" in message:
                logger.warning(
                    "Ollama embeddings endpoint returned 404 for model '%s'", EMBED_MODEL
                )
                raise HTTPException(
                    status_code=503,
                    detail=(
                        f"Embedding model '{EMBED_MODEL}' is not available on the Ollama backend. "
                        "Pull the model or adjust EMBED_MODEL before retrying."
                    ),
                ) from exc
            logger.exception("Embedding provider raised ValueError")
            raise
        except Exception:  # pragma: no cover - defensive logging
            logger.exception("Unexpected failure while requesting embeddings")
            raise

        meta_mappings = cast(list[Mapping[str, Any]], meta_to_add)
        embeddings_seq = cast(list[Sequence[float]], embs_to_add)
        collection.add(
            documents=docs_to_add,
            ids=ids_to_add,
            metadatas=meta_mappings,
            embeddings=embeddings_seq,
        )
        _record_ingest_metrics(True)
        _record_ingest_outcome(req.source_type, modality_label, "success")
        return {
            "status": "ok",
            "added": len(ids_to_add),
            "skipped": len(existing_ids),
        }
    except HTTPException as exc:
        _record_ingest_metrics(False)
        _record_ingest_outcome(req.source_type, modality_label, f"http_{exc.status_code}")
        raise
    except Exception as exc:
        _record_ingest_metrics(False)
        _record_ingest_outcome(req.source_type, modality_label, "error")
        raise HTTPException(
            status_code=500, detail=f"Erreur d'ingestion dans ChromaDB: {exc}"
        ) from exc


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.get("/metrics")
def metrics() -> Response:
    if not ingest_metrics.METRICS_ENABLED:
        raise HTTPException(status_code=404, detail="Metrics disabled")
    body = ingest_metrics.generate_latest(METRIC_REGISTRY)
    return Response(body, media_type=CONTENT_TYPE_LATEST)
