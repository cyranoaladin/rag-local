# Migrating legacy EDU collections

When upgrading an existing deployment, the historical Chroma collection `ressources_pedagogiques_terminale` must be associated with the `edu` tenant without re-indexing content. Follow the steps below on the VPS while the stack is stopped.

1. **Stop services**
   ```bash
   docker compose -f infra/docker-compose.yml --env-file infra/.env down
   ```
2. **Back up** the Chroma volume and admin database (optional but strongly recommended).
   ```bash
   tar -cf backup-$(date +%Y%m%d).tar /srv/rag-admin/admin.db /data/chroma
   ```
3. **Open a Python shell** inside the ingestor container image (or local virtualenv) and run the helper script below. It renames the collection and updates the admin database if necessary.

   ```python
   import chromadb
   from pathlib import Path
   from src.admin.service import AdminService, collection_name_for_tenant

   # 1) Connect to persistent Chroma
   client = chromadb.PersistentClient(path="/data/chroma")
   legacy = client.get_collection("ressources_pedagogiques_terminale")

   # 2) Compute target name and create alias if needed
   target = collection_name_for_tenant("edu", "ressources_pedagogiques_terminale")
   if legacy.name != target:
       client._client._reset()  # ensure metadata reload (Chroma quirk)
       client._client._db.segments[legacy.id].name = target

   # 3) Register the collection inside the admin DB
   service = AdminService()
   folder = service.ensure_folder("edu", "legacy/terminales")
   service.ensure_collection("edu", target, folder=folder)
   print(f"Collection migrated to {target}")
   ```

4. **Restart** the stack and tail the logs for sanity checks.
   ```bash
   docker compose -f infra/docker-compose.yml --env-file infra/.env up -d
   docker compose -f infra/docker-compose.yml logs -f ingestor ui
   ```

## Verification checklist

- `/admin/folders?tenant=edu` exposes the `legacy/terminales` folder.
- `/admin/jobs` returns existing history (if any) and new jobs record under the tenant.
- `/kb/search` with `tenant=edu` returns results from the migrated collection.
- Prometheus `jobs_events_total` shows a non-zero count after running a test ingestion.
