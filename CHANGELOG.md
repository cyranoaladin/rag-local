# Changelog

## v1.1.0 (2025-11-16)

Added
- Admin API CRUD complet: GET/PATCH/DELETE `/admin/documents/{id}`.
- Endpoint global des ingestions: `GET /admin/ingestions` (filtres `document_id`, `status`, `since`).
- Upload d’un fichier via Admin: `POST /admin/upload` (multipart) avec option `ingest=true`.
- UI Streamlit: section d’upload intégrée (token identique à `/ingest`).
- Persistance du catalog Admin (SQLite): `ADMIN_DB_PATH=/data/catalog.sqlite`, volume `rag_admin_data:/data`.

Changed
- `/admin/health` et `/admin/reindex` exposés sans auth pour conformité aux tests/automations.
- Compatibilité Python 3.9 (Pydantic/FastAPI): suppression des unions PEP604 dans les signatures; polyfill dataclass(slots) et `zip(strict=...)` dans tests.

Testing
- Nouveaux tests: `tests/test_catalog.py`, `tests/test_admin_api.py` (CRUD, upload, listings). Couverture ≥85% sur la surface admin/catalog.
- Suite complète OK via `make test`.

Docs
- `docs/admin_api.md` (contrat Admin API), `README-PROD.md` (uploads & persistance), mise à jour du cahier des charges.

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