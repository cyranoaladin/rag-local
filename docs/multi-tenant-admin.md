# Multi-tenant Admin Overview

This document explains how the admin control plane stitches together tenants, folders, taxonomy facets, API keys, and ingestion jobs. All services run on the VPS with no external dependencies.

## SQLite layout

- **Database**: `${ADMIN_DB_PATH}` (defaults to `/srv/rag-admin/admin.db`). The bootstrap routine ensures the parent directory exists and seeds the default tenants `edu` and `web3`.
- **Tables**
  - `tenants`: canonical slug per tenant.
  - `folders`: hierarchical paths (unique per tenant) with optional slug and parent pointer.
  - `collections`: physical Chroma collection names; helper `collection_name_for_tenant()` produces the `${tenant}__slug` naming pattern.
  - `taxonomy_values`: per-tenant facet/value pairs. Defaults bootstrapped for `edu` (`doc_type`, `domain`, `level`, `matiere`, `track`) and for `web3` (`topic`, `chain`, `tool`, `difficulty`). Difficulty is pre-seeded with `beginner`, `intermediate`, `advanced`.
  - `api_keys`: API key metadata (scopes, origin allow-list, optional expiry epoch).
  - `jobs`: ingestion jobs tracking status (`queued|running|done|error`) and source metadata.
  - `job_events`: append-only log powering Server-Sent Events.

## Services and helpers

`src/admin/service.py` centralises all CRUD operations. Highlights:

- `AdminService.ensure_folder()` lazily creates missing hierarchy segments, guaranteeing a collection slug for the leaf folder.
- `AdminService.ensure_collection()` registers the collection row if it does not exist yet.
- `AdminService.create_job()` and `append_job_event()` maintain job/data-plane observability without requiring a separate worker queue.
- `AdminService.list_job_events_since()` powers SSE streaming by returning only events after the last emitted identifier.
- `AdminService.get_job_for_tenant()` enforces tenant isolation when fetching jobs.

`src/common/auth.py` loads API keys from `${API_KEYS_PATH}` and enforces:

- header `X-API-Key` (configurable via `ADMIN_AUTH_HEADER` in the UI) with scope checks;
- per-key origin allow-list (403 if an Origin header does not match);
- token bucket rate-limiting (`RATE_LIMIT_RPM`).

`src/common/sse.py` streams job events as `text/event-stream`, emitting both real events and keep-alive heartbeats. Each event also increments the Prometheus counter `jobs_events_total{tenant,level}`.

## FastAPI router

`src/admin/router.py` exposes the operator surface under `/admin/*`:

- Tenant management (`POST /tenants`).
- Folder CRUD (`GET/POST /folders`).
- Taxonomy values (`GET/POST /taxonomy`).
- API key issuance (`POST /api-keys`).
- One-click ingestion orchestrator (`POST /ingest/oneclick`) which:
  - ensures folder and collection existence;
  - creates an ingestion job with optional idempotency key;
  - appends job events (`queued`, `running`, `done`).
- Job inspection (`GET /jobs`, `/jobs/{job_id}`) and real-time updates (`GET /jobs/{job_id}/events`).

All routes call `_record_metrics()` / `_record_failure()` so Prometheus exposes:

- `admin_requests_total{route,method,code,tenant}`
- `admin_failures_total{route,tenant,reason}`
- `admin_latency_seconds{route}`
- `jobs_events_total{tenant,level}`

## Streamlit operator UI

`src/ui/app.py` now contains dedicated tabs:

1. **Ingestion**: legacy webhook trigger, direct `/ingest` form, and `/admin/ingest/oneclick` form with dynamic taxonomy controls per tenant.
2. **Folders & Taxonomy**: cached listing of folders, creation form, and taxonomy editor.
3. **Jobs**: displays recent jobs and embeds an `EventSource` panel for SSE live updates.
4. **Collections & Search**: existing Chroma explorer (developers can switch to the `/kb/search` API easily).

Environment variables used by the UI:

- `ADMIN_API_BASE`, `ADMIN_API_KEY`, `ADMIN_AUTH_HEADER`, `ADMIN_REQUEST_TIMEOUT`.
- Optional `API_KEY_QUERY_PARAM` and `ADMIN_SSE_TOKEN_PARAM` to surface the API key as a query parameter when your reverse proxy cannot inject custom headers for SSE.

Remember to clear Streamlit caches (`st.cache_data.clear()`) after rotating API keys or adding new taxonomy facets.
