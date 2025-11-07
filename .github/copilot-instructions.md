# Copilot Instructions — rag-local (VPS-friendly RAG)

## Overview
- RAG stack runs as FastAPI ingestor (`src/ingestor/api.py`), Chroma vector DB, optional Ollama embeddings, Streamlit UI (`src/ui/app.py`), and admin APIs (`src/admin/router.py`).
- Data path: ingest request → chunking/embeddings → Chroma collection `ressources_pedagogiques_terminale`; UI/n8n read via REST.
- Compose profiles gate services; defaults `db,llm,api,ui`, add `multimodal` for `raganything` worker and ensure `MULTIMODAL_DEPS=1` during build.

## Core Components
- Ingestor enforces token + optional allowlist via `src/common/auth.py` (`require_api_key`, rate limiter) and MIME/size guards in `_download_*` helpers.
- Multimodal parsing stays behind `MULTIMODAL_ENABLED`; see `src/ingestor/mm_adapter.py` for chunk iterator + SHA256 cache under `/data/mm-cache`.
- Knowledge base router `src/ingestor/search_api.py` exposes search endpoints with Chroma client built from env (`CHROMA_HOST`, `CHROMA_PORT`, timeouts).
- Admin router (tenants/folders/jobs/API keys) lives in `src/admin/`; metrics emitted via `src/ingestor/metrics.py` helpers when `METRICS_ENABLED=true`.

## Running & Tooling
- Bootstrap venv + deps: `make install-dev` (wraps `requirements*.txt`); all make targets auto-select the venv interpreter.
- Bring stack up: `make compose-up` (reads `infra/.env`), add overrides by setting `COMPOSE_PROFILES=db,llm,api,ui` or exporting additional profiles before calling `make`.
- Smoke end-to-end: `bash infra/scripts/smoke.sh` (creates env file, ensures services healthy, seeds Ollama model, runs ingest POST); use `CI=true` to pick CI overrides.
- Observability bundle: `make obs-up` (adds Prometheus via `infra/docker-compose.obs*.yml`), verify with `make obs-quickcheck`.

## Testing Expectations
- Fast tests: `make test` (pytest) and `make typecheck` (mypy); `make test-integration` runs `tests/integration`.
- Security coverage in `tests/test_ingestor_security.py` and `tests/test_kb_search_security.py`; update tests alongside changes touching auth or request validation.
- Metrics gating validated by `tests/test_metrics_*.py`; ensure new metrics respect `METRICS_ENABLED` toggling to keep CI green.

## Patterns & Conventions
- Always stream remote payloads and honor `MAX_REMOTE_BYTES`/`CHROMA_REQUEST_TIMEOUT`; avoid loading full blobs in memory.
- Normalize metadata via `normalize_metadata` and set `metadata.modality` (`text|image|table|formula`); chunking uses `RecursiveCharacterTextSplitter` with size/overlap envs.
- Chroma clients use `chromadb.HttpClient(Settings(..., anonymized_telemetry=False))`; mirror this pattern to avoid telemetry regressions.
- Keep new endpoints under FastAPI router modules and register them in `app.include_router`; wire rate limiting or scope dependencies via `require_api_key`.
- Streamlit UI caches Chroma clients; reuse `src/ui/app.py` idioms (session state, `st.cache_resource`) when extending features.

## Ops Notes
- Env templates live in `infra/.env.example`; production keeps services internal (no `ports:`) and fronted by nginx templates under `infra/nginx/*.template`.
- Admin SQLite and API key JSON paths resolved relative to `/srv/rag-admin`; use helper functions in `src/common/auth.py` instead of hardcoding paths.
- Metrics endpoint `/metrics` returns 404 unless `METRICS_ENABLED=true`; use `infra/scripts/metrics_quickcheck.sh` when validating Prometheus integration.

## Guardrails
- Target low-RAM VPS: prefer iterators/generators, reuse sessions/clients, avoid heavy dependencies in base images without profile flags.
- Respect existing retry and timeout settings; long-running tasks should surface progress via job events (`stream_job_events` SSE).
- When touching Docker, update both base and profile-specific compose files to keep smoke tests functional.
