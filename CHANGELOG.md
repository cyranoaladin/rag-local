# Changelog

## v1.0.0 (2025-11-15)

- Host-managed Nginx: TLS for UI and API, secure headers, /metrics restricted to loopback.
- Removal of n8n from the stack (dev/prod) to simplify and harden production.
- Ingestor API hardened: Authorization: Bearer (X-API-Token compatible), IP allowlist, metrics gating.
- New external Search API: `POST /search` with the same embedding model as indexing for semantic parity.
- Production Compose: loopback bindings, Prometheus optional profile, resource limits and healthchecks.
- CLI ingestion tool for cron jobs: `scripts/ingest-cli.py` (+ requirements-cli).
- CI: Lint, typecheck, tests with coverage gate (≥80% on src/ingestor), and Smoke (Compose) end-to-end.
- Documentation: README-PROD updated, `docs/kb-api.md`, Nginx templates and guide, ops checklist.
- Hardening: Nginx rate limiting for `/ingest` and `/search` (20 r/s, burst 40) in API vhost template.
- Systemd: service template and installer for reliable boot/start/stop of the Compose stack.