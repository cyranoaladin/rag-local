"""Read-only knowledge base API guarded by per-token scopes."""
from __future__ import annotations

import importlib
import logging
import os
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Protocol, cast

import chromadb
from chromadb.utils import embedding_functions
from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel


class AdminDbProtocol(Protocol):
    def normalize_tenant(self, candidate: str | None) -> str: ...
    def api_key_get_by_token(self, token: str, tenant: str) -> dict[str, Any] | None: ...
    def strip_collection_tenant_prefix(self, name: str, tenant: str) -> str: ...
    def canonical_collection_name(self, name: str) -> str: ...
    def collection_name_for_tenant(self, tenant: str, collection: str) -> str: ...

class _FallbackAdminDb:
    _DEFAULT_TENANT = os.getenv("DEFAULT_TENANT", "default") or "default"
    _STATIC_TOKEN = os.getenv("SEARCH_API_TOKEN")

    @classmethod
    def normalize_tenant(cls, candidate: str | None) -> str:
        raw = (candidate or cls._DEFAULT_TENANT).strip().lower()
        sanitized = "".join(ch for ch in raw if ch.isalnum() or ch in {"-", "_"})
        return sanitized or cls._DEFAULT_TENANT

    @classmethod
    def api_key_get_by_token(cls, token: str, tenant: str) -> dict[str, Any] | None:
        expected = (cls._STATIC_TOKEN or "").strip()
        if not expected:
            return None
        if token.strip() != expected:
            return None
        normalized_tenant = cls.normalize_tenant(tenant)
        return {
            "token": expected,
            "tenant": normalized_tenant,
            "scopes": "*",
            "origins": "*",
        }

    @classmethod
    def strip_collection_tenant_prefix(cls, name: str, tenant: str) -> str:
        prefix = f"{cls.normalize_tenant(tenant)}__"
        return name[len(prefix):] if name.startswith(prefix) else name

    @classmethod
    def canonical_collection_name(cls, name: str) -> str:
        cleaned = (name or "").strip().lower().replace(" ", "_")
        sanitized = "".join(ch for ch in cleaned if ch.isalnum() or ch in {"-", "_"})
        return sanitized or "default"

    @classmethod
    def collection_name_for_tenant(cls, tenant: str, collection: str) -> str:
        return f"{cls.normalize_tenant(tenant)}__{cls.canonical_collection_name(collection)}"

logger = logging.getLogger(__name__)

def _load_admin_backend() -> AdminDbProtocol:
    for module_name in ("src.admin.db", "admin.db"):
        try:
            module = importlib.import_module(module_name)
            return cast(AdminDbProtocol, module)
        except ModuleNotFoundError:
            continue
    logger.warning("admin db module not found; falling back to static token checks")
    return cast(AdminDbProtocol, _FallbackAdminDb)

admindb = _load_admin_backend()

router = APIRouter(prefix="/kb", tags=["kb"])

CHROMA_HOST = os.getenv("CHROMA_HOST", "")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000") or "8000")
CHROMA_DIR = os.getenv("CHROMA_DIR", "/data/chroma")
SEARCH_EMBED_MODEL = os.getenv("SEARCH_EMBED_MODEL", "nomic-ai/nomic-embed-text-v1.5")
_reranker_flag = os.getenv("RERANKER_ENABLED")
if _reranker_flag is None:
    _reranker_flag = os.getenv("RERANK_ENABLED", "0")
RERANKER_ENABLED = (_reranker_flag or "0").strip().lower() in {"1", "true", "yes"}
RERANKER_MODEL = os.getenv("RERANKER_MODEL", os.getenv("RERANK_MODEL", "BAAI/bge-reranker-base"))

if TYPE_CHECKING:  # pragma: no cover - typing helper
    from chromadb.api import ClientAPI as _ClientProtocol
else:  # pragma: no cover - runtime fallback
    _ClientProtocol = Any

_client: _ClientProtocol | None = None
_embedder = None
_reranker = None

def _client_lazy() -> _ClientProtocol:
    global _client
    if _client is not None:
        return _client
    if CHROMA_HOST:
        _client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    else:
        _client = chromadb.PersistentClient(path=CHROMA_DIR)
    return _client

def _embedder_lazy() -> Any:
    global _embedder
    if _embedder is None:
        _embedder = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=SEARCH_EMBED_MODEL)
    return _embedder

def _collection(name: str) -> Any:
    return _client_lazy().get_or_create_collection(name=name, embedding_function=_embedder_lazy())

def _resolve_tenant(request: Request) -> str:
    candidate = (
        request.query_params.get("tenant")
        or request.headers.get("X-Tenant")
        or request.headers.get("x-tenant")
    )
    return admindb.normalize_tenant(candidate)

def _check_key(token: str | None, origin: str | None, tenant: str) -> dict[str, Any]:
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing X-API-Key header")
    record = admindb.api_key_get_by_token(token, tenant=tenant)
    if not record:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
    record_tenant = admindb.normalize_tenant(record.get("tenant"))
    if record_tenant != tenant:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "API key not allowed for this tenant")
    scopes = {scope.strip() for scope in (record.get("scopes") or "").split(",") if scope.strip()}
    if scopes and "*" not in scopes and "search" not in scopes:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient scope")
    origins = {orig.strip() for orig in (record.get("origins") or "*").split(",") if orig.strip()}
    if origin and "*" not in origins and origin not in origins:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Origin '{origin}' not allowed for this key")
    return record

class SearchQuery(BaseModel):
    q: str
    collection: str
    k: int = 6
    include_documents: bool = True
    rerank: bool | None = None

@router.get("/collections")
def list_collections(request: Request, x_api_key: str | None = Header(default=None)) -> dict[str, Any]:
    tenant = _resolve_tenant(request)
    _check_key(x_api_key, request.headers.get("origin"), tenant)
    client = _client_lazy()
    raw_collections = client.list_collections()
    names: list[dict[str, Any]] = []
    entries = raw_collections if isinstance(raw_collections, list) else [raw_collections]
    for entry in entries:
        if isinstance(entry, dict):
            name = entry.get("name")
        elif isinstance(entry, str):
            name = entry
        else:
            name = getattr(entry, "name", None)
        if not isinstance(name, str) or not name:
            continue
        if not name.startswith(f"{tenant}__"):
            continue
        base = admindb.strip_collection_tenant_prefix(name, tenant)
        names.append({"name": base, "fullName": name})
    return {"collections": names}

@router.post("/search")
def search(
    payload: SearchQuery,
    request: Request,
    x_api_key: str | None = Header(default=None),
) -> dict[str, Any]:
    tenant = _resolve_tenant(request)
    _check_key(x_api_key, request.headers.get("origin"), tenant)
    if not payload.collection:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing collection name")
    raw_collection = (payload.collection or "").strip()
    if "__" in raw_collection and not raw_collection.startswith(f"{tenant}__"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Collection not allowed for this tenant")
    base_collection = admindb.strip_collection_tenant_prefix(raw_collection, tenant)
    collection_base = admindb.canonical_collection_name(base_collection)
    collection_full = admindb.collection_name_for_tenant(tenant, collection_base)
    k = max(1, min(payload.k, 50))
    collection = _collection(collection_full)
    results = collection.query(query_texts=[payload.q], n_results=k)
    documents = results.get("documents", [[]])[0] if results.get("documents") else []
    metadatas = results.get("metadatas", [[]])[0] if results.get("metadatas") else []
    ids = results.get("ids", [[]])[0] if results.get("ids") else []
    distances = results.get("distances", [[]])[0] if results.get("distances") else []

    rerank_scores: list[float] | None = None
    use_rerank = payload.rerank if payload.rerank is not None else RERANKER_ENABLED
    if use_rerank and documents:
        try:
            global _reranker
            if _reranker is None:
                from sentence_transformers import CrossEncoder
                _reranker = CrossEncoder(RERANKER_MODEL)
            pairs = [(payload.q, doc) for doc in documents]
            raw_scores_any = _reranker.predict(pairs)
            tolist_method = getattr(raw_scores_any, "tolist", None)
            raw_values = tolist_method() if callable(tolist_method) else raw_scores_any
            is_text_value = isinstance(raw_values, str) or isinstance(raw_values, bytes)
            if not isinstance(raw_values, Iterable) or is_text_value:
                raw_values_iterable: Iterable[Any] = [raw_values]
            else:
                raw_values_iterable = raw_values
            scores_list: list[float] = [float(value) for value in raw_values_iterable]
            order = sorted(range(len(documents)), key=scores_list.__getitem__, reverse=True)
            documents = [documents[idx] for idx in order]
            metadatas = [metadatas[idx] for idx in order]
            ids = [ids[idx] for idx in order]
            original_distances = distances
            distances = [
                original_distances[idx] if idx < len(original_distances) else None
                for idx in order
            ]
            rerank_scores = [scores_list[idx] for idx in order]
        except Exception:  # pragma: no cover - reranker is optional
            rerank_scores = None

    hits: list[dict[str, Any]] = []
    for idx, doc_id in enumerate(ids):
        item: dict[str, Any] = {"id": doc_id, "metadata": metadatas[idx] if idx < len(metadatas) else {}}
        if payload.include_documents and idx < len(documents):
            item["document"] = documents[idx]
        if distances and idx < len(distances) and distances[idx] is not None:
            item["score"] = distances[idx]
        if rerank_scores and idx < len(rerank_scores):
            item["rerank_score"] = rerank_scores[idx]
        hits.append(item)
    response: dict[str, Any] = {
        "query": payload.q,
        "collection": collection_base,
        "targetCollection": collection_full,
        "tenant": tenant,
        "k": k,
        "hits": hits,
    }
    return response
