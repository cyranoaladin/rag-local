# Copilot Instructions - RAG VPS Project

## Architecture Overview
This is a CPU-only RAG (Retrieval-Augmented Generation) system with strict VPS resource constraints:
- **Ingestor**: FastAPI service (`src/ingestor/api.py`) that processes documents and generates embeddings
- **UI**: Streamlit dashboard (`src/ui/app.py`) for search and ingestion management  
- **Chroma**: Vector database for embeddings storage (`ressources_pedagogiques_terminale` collection)
- **Ollama**: CPU-only embeddings model (`nomic-embed-text`) and LLM serving
- **n8n**: Optional workflow automation for scheduled ingestion
- **Nginx**: Reverse proxy with TLS termination

## Development Workflow

### Quick Start Commands
```bash
# Setup environment
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp infra/.env.example infra/.env

# Start dev stack (auto-detects docker-compose.dev.yml)
make compose-up        # or make up
make logs              # monitor services

# Quality checks
make lint typecheck test smoke

# Nginx web service (separate profile)
make nginx-up nginx-smoke nginx-reload nginx-down
```

### Service Architecture Pattern
- All services listen on loopback only in production (`127.0.0.1:port`)
- Dev overrides expose ports: ingestor `18001`, UI `18501`, nginx `18080`
- External access only via Nginx + TLS in production
- Use `COMPOSE_PROFILES=web` to enable nginx service

## Code Patterns & Constraints

### Performance & Resource Limits
- **Ingestor RAM**: ≤ 250 MiB under load, **UI RAM**: ≤ 200 MiB at rest
- Prefer CPU-only dependencies; reject GPU libraries without documented justification
- Use O(n log n) algorithms or better; avoid memory copies (prefer generators/streaming)
- Document chunking: 800 chars with 120 overlap (`INGEST_CHUNK_SIZE`/`INGEST_CHUNK_OVERLAP`)

### Network & Security Patterns
- All network timeouts ≤ 10s with bounded retries (`HTTP_TIMEOUT`, `OLLAMA_EMBED_TIMEOUT`) 
- Token auth via `X-API-Token` header + CIDR allowlist for ingestor
- Never expose secrets in logs or user interfaces
- Max download size: `MAX_REMOTE_BYTES` (default 10 MiB)

### Error Handling & Resilience
- Network errors must never be ignored - always implement retries with bounds
- Use `requests.raise_for_status()` pattern consistently
- Ollama/Chroma clients have dedicated retry logic (`OLLAMA_MAX_RETRIES`, `CHROMA_MAX_RETRIES`)
- Health checks use raw TCP sockets for minimal overhead

### File Organization Conventions
- Environment configs in `infra/.env` (copy from `infra/.env.example`)
- Docker compose: base `infra/docker-compose.yml` + dev override `infra/docker-compose.dev.yml`
- Nginx templates in `infra/nginx/*.template` rendered to `infra/nginx/rendered/`
- n8n workflows: examples in `n8n/workflows/examples/`, production in `n8n/workflows/prod/`

### Testing & Validation
- `scripts/smoke.sh`: Full integration test (requires running stack + API token)
- Quality tools: `ruff` (linting), `mypy` (typing), `pylint` (additional checks), `pytest`
- Use `docker inspect` for health status checks in scripts
- Cache Streamlit resources with `@st.cache_resource` / `@st.cache_data(ttl=30)`
