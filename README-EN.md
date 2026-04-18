# rag-local — Complete Documentation (EN)

**Author: Alaeddine BEN RHOUMA**

---

## Overview

`rag-local` is a 100% local RAG (Retrieval-Augmented Generation) solution, designed for VPS (no GPU required), with modular architecture: resource ingestion (web, files, GDrive), vector indexing (ChromaDB), local embeddings & LLM (Ollama), search UI (Streamlit), automations (n8n, optional), and Prometheus observability. Everything is orchestrated by Docker Compose, secured by Nginx, and production-ready.

**Goals:**
- Zero cloud/LLM dependency
- Controlled RAM/CPU (VPS-friendly)
- Security (auth, allowlist, reverse proxy)
- Robust observability & CI/CD

---

## Architecture

```
[n8n/UI] --HTTP--> [Ingestor FastAPI] --RPC--> [Ollama Embeddings]
                                      \--REST--> [ChromaDB]
                                             \--> [Streamlit UI]
```

- **Ingestor** (FastAPI): `/ingest` (URL, files, GDrive), `/health`, `/metrics` (Prometheus)
- **ChromaDB**: vector storage, single collection
- **Ollama**: embeddings (`nomic-embed-text`), LLM (`llama3.2`)
- **UI** (Streamlit): semantic search, top-k, metadata
- **n8n** (optional): automations, webhooks, scheduling
- **Nginx**: reverse proxy, TLS, security headers
- **Prometheus** (optional): observability, alerts

See `docs/dossier-technique-exhaustif.md` and `SPEC.md` for all details (API, variables, security, flows, Compose profiles).

---

## Local Installation & Usage (Development)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp infra/.env.example infra/.env
# Edit variables (tokens, ports, Ollama models...)
docker compose -f infra/docker-compose.yml --env-file infra/.env up -d --remove-orphans
bash infra/scripts/smoke.sh  # health + dummy ingestion
```

Quality:
- `make lint` (ruff)
- `make typecheck` (mypy)
- `make test` (pytest)
- `make smoke` (stack + health)

Stop:
```bash
docker compose -f infra/docker-compose.yml --env-file infra/.env down --remove-orphans
```

---

## Production Deployment (VPS)

1. Clone the repo on the VPS (`/srv/rag-local` recommended)
2. Copy `infra/.env.example` → `infra/.env` and fill all variables (see Security section)
3. Generate secrets (see table below)
4. Prepare GDrive credentials if needed (`/srv/rag/creds/gdrive-service-account.json`)
5. Render Nginx vhosts with `envsubst` and enable TLS with certbot
6. Deploy:
   ```bash
   cd /srv/rag-local
   sudo scripts/deploy-prod.sh
   ```

**Secrets to generate:**
| Name | Length | Usage |
|------|--------|-------|
| `INGEST_AUTH_TOKEN` | 64 hex | Auth `/ingest` |
| `INGESTOR_API_TOKEN` | 64 hex | UI ↔ API |
| `N8N_ENCRYPTION_KEY` | 64 hex | n8n credentials |
| `N8N_BASIC_AUTH_PASSWORD` | 32 | n8n UI |
| `PROMETHEUS_SCRAPE_PASSWORD` | 32 | /metrics |

**Ollama models:** `nomic-embed-text`, `llama3.2:3b` (preload via `infra/scripts/ollama-preload.sh`)

---

## Security & Best Practices

- Token authentication on `/ingest` (configurable header)
- CIDR IP allowlist (prod)
- Uploaded files: MIME whitelist, restricted root
- Nginx: BasicAuth, TLS, CSP/HSTS headers
- Secrets outside VCS, 600 permissions on credentials
- Never expose Compose ports directly in production

---

## Observability & Metrics

- Prometheus endpoint `/metrics` (ingestor), enable with `METRICS_ENABLED=true`
- Metrics: `ingestor_ingests_total{source,modality,status}`, `ingestor_ingest_duration_seconds`
- Compose profile `obs` for local Prometheus
- Recommended PromQL alerts (see `docs/observability.md`)

---

## CI/CD & Software Quality

- GitHub Actions pipeline: lint, typecheck, tests, smoke
- Script `infra/scripts/smoke.sh`: health check, logs, auto-diagnostic on failure
- Robustness: all logs, network state, inspect are dumped on CI fail
- Unit and integration tests cover security, chunking, metrics, multimodal

---

## FAQ & Further Resources

- Architecture: `docs/architecture.md`, `docs/dossier-technique-exhaustif.md`
- API & variables: `SPEC.md`
- Observability: `docs/observability.md`
- CI/CD & robustness: `CI_ROBUSTESSE.md`
- Copilot instructions: `.github/copilot-instructions.md`

---

## Author

This guide was written and maintained by **Alaeddine BEN RHOUMA** to ensure understanding, robustness, and maintainability of the rag-local project in production.
