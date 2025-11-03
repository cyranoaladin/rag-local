# Webhooks n8n → Parité FastAPI

Les routes suivantes remplacent les webhooks n8n et permettent une exploitation 100% locale:
- `POST /ingest/source` : ingestion via JSON (URL/texte)
- `POST /ingest` (upload) : ingestion de fichiers, MIME whitelistée
- `POST /admin/reindex` : réindexation batch (implémentation existante/à activer)
Utiliser `cron` ou `Make` pour l orchetration en lieu et place d n8n.
