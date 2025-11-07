"""Read-only knowledge base API guarded by API-key scopes."""
from __future__ import annotations

import importlib
import os
import time
from collections.abc import Iterable, Sequence
from typing import Annotated, Any, Protocol, cast

import chromadb
from chromadb.api import ClientAPI
from chromadb.utils import embedding_functions
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from src.admin.service import (
    AdminService,
    canonical_collection_name,
    collection_name_for_tenant,
    default_service,
    strip_collection_tenant_prefix,
)
from src.common.auth import AuthContext, require_api_key

router = APIRouter(prefix="/kb", tags=["kb"])
CHROMA_HOST = os.getenv("CHROMA_HOST", "")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8000") or "8000")
CHROMA_DIR = os.getenv("CHROMA_DIR", "/data/chroma")
SEARCH_EMBED_MODEL = os.getenv("SEARCH_EMBED_MODEL", "nomic-ai/nomic-embed-text-v1.5")
DEFAULT_COLLECTION_BASE = os.getenv("DEFAULT_COLLECTION_BASE", "ressources_pedagogiques_terminale")
_reranker_flag = os.getenv("RERANKER_ENABLED")
if _reranker_flag is None:
	_reranker_flag = os.getenv("RERANK_ENABLED", "0")
RERANKER_ENABLED = (_reranker_flag or "0").strip().lower() in {"1", "true", "yes"}
RERANKER_MODEL = os.getenv("RERANKER_MODEL", os.getenv("RERANK_MODEL", "BAAI/bge-reranker-base"))

_client: ClientAPI | None = None
_embedder: Any | None = None
class RerankerProtocol(Protocol):
	def predict(
		self, pairs: Sequence[tuple[str, str]] | Iterable[tuple[str, str]]
	) -> Any:  # pragma: no cover - protocol definition
		...


_reranker: RerankerProtocol | None = None
_SERVICE = default_service()


def get_service() -> AdminService:
	return _SERVICE


ServiceDep = Annotated[AdminService, Depends(get_service)]
AuthKBRead = Annotated[AuthContext, Depends(require_api_key(["kb:read"]))]


def _client_lazy() -> ClientAPI:
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


def _init_reranker() -> RerankerProtocol | None:
	try:
		module = importlib.import_module("sentence_transformers")
	except ImportError:
		return None
	cross_encoder_cls = getattr(module, "CrossEncoder", None)
	if cross_encoder_cls is None:
		return None
	try:
		instance = cross_encoder_cls(RERANKER_MODEL)
	except Exception:
		return None
	return cast(RerankerProtocol, instance)


def _ensure_reranker() -> RerankerProtocol | None:
	global _reranker
	if _reranker is None:
		_reranker = _init_reranker()
	return _reranker

class SearchQuery(BaseModel):
	q: str = Field(..., description="User query")
	collection: str | None = Field(default=None, description="Collection alias or full name")
	k: int = Field(default=6, ge=1, le=50)
	include_documents: bool = True
	rerank: bool | None = None
	filters: dict[str, str] | None = None

def _record_metrics(route: str, request: Request, tenant: str, status_code: int, start: float) -> None:
	metrics = importlib.import_module("src.ingestor.metrics")
	if not metrics.METRICS_ENABLED:
		return
	requests, _, latency = metrics.get_kb_metrics()
	requests.labels(route=route, method=request.method, code=str(status_code), tenant=tenant).inc()
	latency.labels(route=route).observe(time.perf_counter() - start)


def _record_failure(route: str, tenant: str, reason: str) -> None:
	metrics = importlib.import_module("src.ingestor.metrics")
	if not metrics.METRICS_ENABLED:
		return
	_, failures, _ = metrics.get_kb_metrics()
	failures.labels(route=route, tenant=tenant, reason=reason).inc()

@router.get("/collections")
def list_collections(
	request: Request,
	auth: AuthKBRead,
	service: ServiceDep,
) -> dict[str, Any]:
	start = time.perf_counter()
	collections = service.list_collections(auth.tenant)
	items: list[dict[str, Any]] = []
	for entry in collections:
		base = strip_collection_tenant_prefix(entry.name, auth.tenant)
		items.append({"name": base, "fullName": entry.name, "folderId": entry.folder_id})
	_record_metrics("kb.collections", request, auth.tenant, 200, start)
	return {"tenant": auth.tenant, "collections": items}

def _resolve_collection_name(
	service: AdminService,
	auth: AuthContext,
	payload: SearchQuery,
) -> tuple[str, str]:
	if payload.collection:
		candidate = payload.collection.strip()
		if "__" in candidate and not candidate.startswith(f"{auth.tenant}__"):
			raise HTTPException(status.HTTP_403_FORBIDDEN, "Collection not allowed for this tenant")
		base_name = strip_collection_tenant_prefix(candidate, auth.tenant)
	else:
		filters = payload.filters or {}
		folder_path = filters.get("folder_path") or filters.get("folder")
		if folder_path:
			folder = service.get_folder_by_path(auth.tenant, folder_path)
			if folder is None:
				raise HTTPException(status.HTTP_404_NOT_FOUND, "Folder not found")
			base_name = canonical_collection_name(folder.path)
		else:
			base_name = canonical_collection_name(DEFAULT_COLLECTION_BASE)
	collection_full = collection_name_for_tenant(auth.tenant, base_name)
	return base_name, collection_full

@router.post("/search")
def search(
	payload: SearchQuery,
	request: Request,
	auth: AuthKBRead,
	service: ServiceDep,
) -> dict[str, Any]:
	start = time.perf_counter()
	try:
		base_collection, target_collection = _resolve_collection_name(service, auth, payload)
	except HTTPException as exc:
		_record_failure("kb.search", auth.tenant, str(exc.detail))
		raise
	collection = _collection(target_collection)
	k = max(1, min(payload.k, 50))
	results = collection.query(query_texts=[payload.q], n_results=k)
	documents = results.get("documents", [[]])[0] if results.get("documents") else []
	metadatas = results.get("metadatas", [[]])[0] if results.get("metadatas") else []
	ids = results.get("ids", [[]])[0] if results.get("ids") else []
	distances = results.get("distances", [[]])[0] if results.get("distances") else []

	rerank_scores: list[float] | None = None
	use_rerank = payload.rerank if payload.rerank is not None else RERANKER_ENABLED
	if use_rerank and documents:
		try:
			reranker = _ensure_reranker()
			if reranker is None:
				raise RuntimeError("Reranker unavailable")
			pairs = [(payload.q, doc) for doc in documents]
			raw_scores_any = reranker.predict(pairs)
			tolist_method = getattr(raw_scores_any, "tolist", None)
			raw_values = tolist_method() if callable(tolist_method) else raw_scores_any
			if isinstance(raw_values, str | bytes):
				raw_iterable: Iterable[Any] = [raw_values]
			elif isinstance(raw_values, Iterable):
				raw_iterable = raw_values
			else:
				raw_iterable = [raw_values]
			scores_list = [float(value) for value in raw_iterable]
			order = sorted(range(len(documents)), key=scores_list.__getitem__, reverse=True)
			documents = [documents[idx] for idx in order]
			metadatas = [metadatas[idx] for idx in order]
			ids = [ids[idx] for idx in order]
			distances = [distances[idx] if idx < len(distances) else None for idx in order]
			rerank_scores = [scores_list[idx] for idx in order]
		except Exception:  # pragma: no cover - reranker optional at runtime
			rerank_scores = None

	hits: list[dict[str, Any]] = []
	for idx, doc_id in enumerate(ids):
		metadata = metadatas[idx] if idx < len(metadatas) else {}
		item: dict[str, Any] = {"id": doc_id, "metadata": metadata}
		if payload.include_documents and idx < len(documents):
			item["document"] = documents[idx]
		if distances and idx < len(distances) and distances[idx] is not None:
			item["score"] = distances[idx]
		if rerank_scores and idx < len(rerank_scores):
			item["rerank_score"] = rerank_scores[idx]
		hits.append(item)

	_record_metrics("kb.search", request, auth.tenant, 200, start)
	return {
		"query": payload.q,
		"collection": base_collection,
		"targetCollection": target_collection,
		"tenant": auth.tenant,
		"k": k,
		"hits": hits,
	}
