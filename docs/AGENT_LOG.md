# Agent Log

Entrées horodatées des actions d’agent liées au projet.

## 2025-11-16
- Implémentation Admin API CRUD complet (GET/PATCH/DELETE /admin/documents/{id}).
- Ajout endpoint global des ingestions (GET /admin/ingestions) et upload (POST /admin/upload) avec ingestion optionnelle.
- UI Streamlit: ajout d’un écran d’upload relié à /admin/upload.
- Infra prod: persistance du catalog (ADMIN_DB_PATH=/data/catalog.sqlite) et volume rag_admin_data:/data; /data/uploads monté en rw.
- Compatibilité Python 3.9: 
  - models Pydantic/paramètres FastAPI: Optional[...] au lieu de unions PEP604,
  - mm_adapter: polyfill dataclass(slots) et isinstance(bytes|bytearray) → isinstance((bytes, bytearray)),
  - tests: zip(..., strict=False) → zip(...).
- Tests ajoutés (catalog, admin_api) + exécution complète `make test`: OK.
- Docs mises à jour: CHANGELOG v1.1.0, README-PROD (uploads & persistance), admin_api.md, cahier des charges (statut V1).
