# External API contract

This document summarises the public HTTP surface available to automation clients once an API key has been issued. All routes require:

- Header `X-API-Key: <token>` (unless your reverse proxy injects the key).
- Optional query `tenant=<slug>` to override the default tenant (`DEFAULT_TENANT`, `edu` by default).
- Origin header authorised by the API key allow-list when requests originate from a browser.
- Compliance with the per-key rate limit (`RATE_LIMIT_RPM`). Exceeding the budget returns `429 Too Many Requests`.

## Admin endpoints (`/admin/*`)

| Route | Method | Scope(s) | Description |
| --- | --- | --- | --- |
| `/admin/tenants` | `POST` | `keys:issue` | Create a new tenant slug (idempotent).
| `/admin/folders` | `GET` | `folders:read` | List folders for the tenant. Accepts `tenant`, `parent_id` query params. |
| `/admin/folders` | `POST` | `folders:write` | Ensure a folder hierarchy exists. Body `{tenant, path, slug?}`. Returns folder metadata plus collection name. |
| `/admin/taxonomy` | `GET` | `folders:read` | Retrieve taxonomy facets and recorded values for the tenant. |
| `/admin/taxonomy` | `POST` | `folders:write` | Append a new taxonomy value. Body `{tenant, facet, value}`. |
| `/admin/api-keys` | `POST` | `keys:issue` | Issue (or rotate) an API key. Body `{tenant, scopes[], origins[], expires_at?}`. |
| `/admin/ingest/oneclick` | `POST` | `folders:write`, `ingest:write` | Orchestrate ingestion for a single source. See payload below. |
| `/admin/jobs` | `GET` | `jobs:read` | List recent jobs. Optional `status`, `limit`. |
| `/admin/jobs/{job_id}` | `GET` | `jobs:read` | Retrieve job metadata (tenant enforced). |
| `/admin/jobs/{job_id}/events` | `GET` | `jobs:read` | Server-Sent Events stream of job updates. |

### One-click ingestion payload

```json
{
  "tenant": "web3",
  "folder_path": "guides/solidity/basics",
  "source_type": "url",
  "source_value": "https://example.org/tutorial",
  "taxonomy": {
    "topic": "solidity",
    "chain": "evm",
    "tool": "foundry",
    "difficulty": "beginner"
  },
  "mode": "text",
  "idempotency_key": "optional-stable-id"
}
```

Success returns `202 Accepted` with the job identifier, resolved collection name, and the metadata snapshot that was attached to the job record.

### SSE stream contract

`GET /admin/jobs/{job_id}/events?tenant=<slug>` responds with `text/event-stream`. Each `message` event uses the structure:

```json
{
  "id": "17",
  "job_id": "job-sse-1",
  "timestamp": "2025-11-07T10:13:12.341829+00:00",
  "level": "info",
  "message": "Ingestion completed for folder 'guides/solidity/basics'"
}
```

`keepalive` events carry `{ "job_id": "..." }` every ~15 seconds to keep the connection open.

To authenticate SSE traffic from a browser, either:

1. Configure your reverse proxy (e.g. Nginx) to inject `X-API-Key` headers for the `/admin/jobs/*/events` path, **or**
2. Expose the UI-provided query parameter fallback by setting `API_KEY_QUERY_PARAM` (backend) and `ADMIN_SSE_TOKEN_PARAM` (UI). The UI will append `&<param>=<urlencoded key>` automatically.

## Knowledge base search (`/kb/search`)

- Scope: `kb:read`.
- Body schema:

```json
{
  "q": "how to compute a derivative",
  "k": 6,
  "filters": {"folder_path": "guides/math"},
  "include_documents": true,
  "rerank": false
}
```

- The API enforces origin allow-lists, rate limits, and optional reranking:
  - Global flag `RERANKER_ENABLED` (`false` by default).
  - Request-level override via the `rerank` boolean field.
  - The reranker loads on demand via `sentence_transformers.CrossEncoder`. If the library is not present or the model cannot load, the endpoint gracefully falls back to original ordering.

## Metrics

All endpoints expose Prometheus metrics (when `METRICS_ENABLED=true`) under `/metrics`:

- `admin_requests_total` / `admin_latency_seconds` / `admin_failures_total`
- `kb_search_requests_total` / `kb_search_latency_seconds` / `kb_search_failures_total`
- `jobs_events_total{tenant,level}` for SSE traffic

Combined with existing ingest metrics you can build dashboards covering end-to-end ingestion latencies, error rates, and job activity.
