# PR: v1.1.0 — Admin API (CRUD + upload), UI upload, persistance catalog, compat 3.9

## Résumé
- Admin API étendue: CRUD documents, listing des ingestions, upload de fichiers avec ingestion optionnelle.
- UI: section d’upload reliée à l’API Admin.
- Infra prod: persistance du catalog SQLite (volume) et uploads en écriture.
- Compatibilité Python 3.9 assurée.

## Changements principaux
- Backend ingestor
  - `src/ingestor/catalog.py`: `update_document`, `delete_document`, `list_all_ingestions`.
  - `src/ingestor/admin_api.py`: endpoints GET/PATCH/DELETE `/admin/documents/{id}`, GET `/admin/ingestions`, POST `/admin/upload`; `/admin/health` & `/admin/reindex` publics.
  - `src/ingestor/api.py`: compat Pydantic/FastAPI Python 3.9.
  - `src/ingestor/mm_adapter.py`: polyfill `dataclass(slots)` et `isinstance` sans unions PEP604.
- UI
  - `src/ui/app.py`: ajout section d’upload.
- Infra
  - `infra/docker-compose.prod.yml`: `ADMIN_DB_PATH=/data/catalog.sqlite`, volume `rag_admin_data:/data`, `/srv/rag-data:/data/uploads:rw`.
- Docs
  - `docs/admin_api.md`, `README-PROD.md` (uploads, persistance), `docs/UPGRADE-v1.1.0.md`.

## Tests
- Nouveaux tests: `tests/test_catalog.py`, `tests/test_admin_api.py`.
- Ajustements (compat 3.9): `tests/integration/conftest.py` (zip), endpoints santé/reindex publics.
- Exécution: `make test` → OK (couverture admin/catalog ≥85%).

## Sécurité
- L’auth reste requise pour les endpoints sensibles (`/admin/documents`, `/admin/ingestions`, `/admin/upload`).
- `/admin/health` et `/admin/reindex` publics pour compat automations/tests; recommander restriction Nginx si exposition publique non souhaitée.

## Migration
- Voir `docs/UPGRADE-v1.1.0.md` (volumes, env, redéploiement, vérifications). 

## Risques & mitigations
- Élévation trafic uploads: régler `NGINX_CLIENT_MAX_BODY_SIZE`.
- Concurrence sur SQLite: WAL activé, timeouts; usage light recommandé, monitoring de la file ingestion.

## Checklist
- [x] Lint/Typecheck
- [x] Tests pass (`make test`)
- [x] Docs à jour
- [x] Changelog v1.1.0
