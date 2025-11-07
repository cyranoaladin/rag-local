"""API key management, dynamic CORS, and request-scoped auth helpers."""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from .ratelimit import TokenBucketLimiter

_HEADER_API_KEY = "X-API-Key"
_DEFAULT_RATE = 240
_DEFAULT_TENANT = "edu"
_KEYS_ENV = "API_KEYS_PATH"
_DB_ENV = "ADMIN_DB_PATH"
_RATE_ENV = "RATE_LIMIT_RPM"
_QUERY_PARAM_ENV = "API_KEY_QUERY_PARAM"


@dataclass
class APIKeyRecord:
    key: str
    tenant: str
    scopes: set[str]
    origins: set[str]
    note: str | None
    expires_at: float | None


@dataclass
class AuthContext:
    tenant: str
    key: str
    scopes: set[str]
    record: APIKeyRecord


class APIKeyStore:
    """Loads API keys from a JSON file with mtime-aware caching."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._mtime: float | None = None
        self._cache: dict[str, APIKeyRecord] = {}

    def _load(self) -> dict[str, APIKeyRecord]:
        if not self._path.exists():
            return {}
        try:
            with self._path.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise RuntimeError(f"Invalid API key JSON: {exc}") from exc
        cache: dict[str, APIKeyRecord] = {}
        for key, payload in raw.items():
            tenant = str(payload.get("tenant", "")).strip().lower()
            if not tenant:
                continue
            scopes_iter: Iterable[str] = payload.get("scopes") or []
            if isinstance(scopes_iter, str):
                scopes_iter = [scope.strip() for scope in scopes_iter.split(",")]
            scopes = {scope.strip() for scope in scopes_iter if scope.strip()}
            origins_iter: Iterable[str] = payload.get("origins") or ["*"]
            if isinstance(origins_iter, str):
                origins_iter = [origins_iter]
            origins = {origin.strip() for origin in origins_iter if origin.strip()}
            note = payload.get("note")
            expires_at_raw = payload.get("expires_at")
            if expires_at_raw:
                try:
                    expires_at = float(expires_at_raw)
                except (TypeError, ValueError):
                    expires_at = None
            else:
                expires_at = None
            record = APIKeyRecord(
                key=key,
                tenant=tenant,
                scopes=scopes,
                origins=origins or {"*"},
                note=note,
                expires_at=expires_at,
            )
            cache[key] = record
        return cache

    def get(self, key: str) -> APIKeyRecord | None:
        stat_mtime = None
        if self._path.exists():
            stat_mtime = self._path.stat().st_mtime
        with self._lock:
            if self._mtime is None or stat_mtime and stat_mtime > self._mtime:
                self._cache = self._load()
                self._mtime = stat_mtime
            return self._cache.get(key)

    def dump(self) -> dict[str, APIKeyRecord]:
        with self._lock:
            if not self._cache:
                self._cache = self._load()
                self._mtime = self._path.stat().st_mtime if self._path.exists() else None
            return dict(self._cache)


_manager: APIKeyStore | None = None
_limiter: TokenBucketLimiter | None = None
_manager_lock = threading.Lock()


def _default_keys_path() -> Path:
    raw = os.getenv(_KEYS_ENV, "/srv/rag-admin/api_keys.json")
    path = Path(raw)
    if not path.is_absolute():
        base = Path(os.getenv(_DB_ENV, "/srv/rag-admin/admin.db")).resolve().parent
        path = base / path
    return path


def get_key_store() -> APIKeyStore:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = APIKeyStore(_default_keys_path())
    return _manager


def reset_key_store() -> None:
    global _manager
    with _manager_lock:
        _manager = None


def get_rate_limiter() -> TokenBucketLimiter:
    global _limiter
    if _limiter is None:
        rpm = int(os.getenv(_RATE_ENV, str(_DEFAULT_RATE)) or _DEFAULT_RATE)
        if rpm <= 0:
            rpm = _DEFAULT_RATE
        _limiter = TokenBucketLimiter(rate_per_minute=rpm, capacity=float(rpm))
    return _limiter


def reset_rate_limiter() -> None:
    global _limiter
    _limiter = None


def default_tenant() -> str:
    value = os.getenv("DEFAULT_TENANT", _DEFAULT_TENANT)
    return value.strip().lower() or _DEFAULT_TENANT


def normalize_tenant(value: str | None) -> str:
    return (value or default_tenant()).strip().lower() or default_tenant()


def _origin_allowed(record: APIKeyRecord, origin: str | None) -> bool:
    if not origin:
        return True
    origins = record.origins or {"*"}
    if "*" in origins:
        return True
    return origin in origins


def _scopes_allowed(record: APIKeyRecord, scopes: Sequence[str] | None) -> bool:
    if not scopes:
        return True
    scope_set = record.scopes or set()
    if "*" in scope_set:
        return True
    return all(scope in scope_set for scope in scopes)


def _check_expiry(record: APIKeyRecord) -> None:
    if record.expires_at is None:
        return
    if time.time() > record.expires_at:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key expired")


def require_api_key(required_scopes: Sequence[str] | None = None):
    def _dependency(request: Request) -> AuthContext:
        key = request.headers.get(_HEADER_API_KEY) or request.headers.get(_HEADER_API_KEY.lower())
        if not key:
            query_param_name = os.getenv(_QUERY_PARAM_ENV, "").strip()
            if query_param_name:
                key = request.query_params.get(query_param_name)
        if not key:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing API key")
        store = get_key_store()
        record = store.get(key)
        if record is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
        _check_expiry(record)
        tenant_candidate = request.query_params.get("tenant") or request.headers.get("X-Tenant")
        tenant = normalize_tenant(tenant_candidate or record.tenant)
        if tenant != record.tenant:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API key tenant mismatch")
        origin = request.headers.get("Origin")
        if not _origin_allowed(record, origin):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Origin not allowed")
        if not _scopes_allowed(record, required_scopes):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient scope")
        limiter = get_rate_limiter()
        if not limiter.consume(key):
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")
        context = AuthContext(tenant=tenant, key=key, scopes=record.scopes, record=record)
        request.state.auth = context
        return context

    return _dependency


class DynamicCORSMiddleware(BaseHTTPMiddleware):
    """Sets Access-Control headers based on API key origin allowlists."""

    def __init__(self, app: ASGIApp, *, paths: Sequence[str] = ("/admin", "/kb")) -> None:
        super().__init__(app)
        self._paths = tuple(paths)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path
        origin = request.headers.get("Origin")
        if origin and any(path.startswith(prefix) for prefix in self._paths):
            key = request.headers.get(_HEADER_API_KEY) or request.headers.get(_HEADER_API_KEY.lower())
            if not key:
                return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "Missing API key"})
            record = get_key_store().get(key)
            if record is None:
                return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content={"detail": "Invalid API key"})
            if not _origin_allowed(record, origin):
                return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content={"detail": "Origin not allowed"})
            response = await call_next(request)
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers.setdefault("Access-Control-Allow-Headers", "Authorization, Content-Type, X-API-Key")
            response.headers.setdefault("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
            return response
        if request.method == "OPTIONS" and origin:
            response = Response(status_code=status.HTTP_204_NO_CONTENT)
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-API-Key"
            response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
            return response
        return await call_next(request)


def generate_api_key(prefix: str = "rag") -> str:
    token = secrets.token_urlsafe(32)
    return f"{prefix}_{token}"
