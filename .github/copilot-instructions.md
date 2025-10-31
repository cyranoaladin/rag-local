# Copilot Instructions — rag-local (VPS-friendly RAG)

## Architecture (big picture)
- Services: **ingestor** (FastAPI) → **ChromaDB** (vector store) → **ui** (Streamlit). Optional: **ollama** (LLM), **n8n**, **nginx**.
- Data flow: `/ingest` → chunking → embeddings → `ressources_pedagogiques_terminale` collection → UI queries.
- Profiles: default = db,llm,api,ui ; **multimodal** profile adds `raganything` (images/PDF → typed chunks).

## Dev workflow (canonical)
- Build/run: `docker compose -f infra/docker-compose.yml --env-file infra/.env up -d --remove-orphans`  
	Multimodal: add `--profile multimodal` and `MULTIMODAL_DEPS=1` at build time.
- Quality: `make lint` (ruff), `make typecheck` (mypy), `make test` (pytest).  
	Smoke: `bash infra/scripts/smoke.sh` (health + ingest check).
- Nginx: templates in `infra/nginx/*.template` → render via **envsubst** → mount into the proxy container.

## Conventions & patterns
- **Security**: token auth for `/ingest`, optional CIDR allowlist; strict MIME whitelist for uploads (PDF/PNG/JPEG); remote URL allow-list.  
- **Timeouts/Retries**: requests sessions with bounded retries; Ollama/Chroma calls wrapped with timeouts.  
- **Chunking**: configurable size & overlap; normalize metadata; always tag `metadata.modality ∈ {text,image,table,formula}`.  
- **Multimodal**: adapter `src/ingestor/mm_adapter.py` yields `Iterator[Chunk]` (low-RAM) with SHA256+mtime cache under `/data/mm-cache`.  
- **UI**: Streamlit caches Chroma client; limit `top_k`; hide secrets; badges display modality counts.  
- **Compose**: production keeps API/UI/n8n non-exposed (no `ports:`); Nginx fronts services via `${NGINX_*_UPSTREAM}`.  
- **Env**: see `infra/.env.example` (INGEST_BASE_URL, MULTIMODAL_* knobs, NGINX_*_UPSTREAM, etc.).

## How to extend safely
- Add endpoints in `src/ingestor/api.py`; validate via unit tests in `tests/` and the smoke script.  
- For large files, prefer streaming I/O; avoid loading whole payloads in memory; keep iterators/generators.  
- Multimodal: keep parser timeouts (`MM_PARSER_TIMEOUT`), bound chunk size (`MM_MAX_CHARS_PER_CHUNK`), and fallback to text mode on timeout.

## Testing & CI hooks
- Unit targets: `_enforce_security`, `_prepare_chunks_for_chroma`, text‐mode ingest (no external services).  
- Optional Prometheus: expose `/metrics` if `prometheus_client` present.  
- Future CI: run `make lint && make typecheck && make test`; optionally smoke a compose profile behind `workflow_dispatch`.

## Examples
- Dev up (multimodal):  
	`MULTIMODAL_DEPS=1 docker compose -f infra/docker-compose.yml --env-file infra/.env --profile multimodal up -d`
- Render Nginx for prod:  
	`envsubst < infra/nginx/rag-ui.conf.template    > infra/nginx/rendered/rag-ui.conf`  
	`envsubst < infra/nginx/rag-n8n.conf.template   > infra/nginx/rendered/rag-n8n.conf`

## Guardrails (VPS)
- RAM bound mindset: iterators, caches by content hash, reuse clients, avoid O(n^2) scans; prefer O(n log n) or vectorized ops.  
- Never introduce heavy deps in the API image without a profile flag; keep defaults lean.
