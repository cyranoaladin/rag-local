"""Entry point for the dashboard backend FastAPI application."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.config import get_settings
from .core.db import init_db
from .routers import auth, users


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="rag-local dashboard API", lifespan=lifespan)


settings = get_settings()

# Ensure SQLite in-memory databases used during tests get initialized eagerly.
if settings.database_url.startswith("sqlite") and ":memory:" in settings.database_url:
    init_db()

if settings.cors_allow_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(users.router, prefix="/users", tags=["users"])


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
