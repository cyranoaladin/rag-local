# SPEC — rag-local

## Architecture

* **Chroma (DB v2)**: stockage embeddings + métadonnées.
* **Ollama**: embeddings (nomic-embed-text), LLM (llama3.2).
* **Ingestor (FastAPI)**: /health, /ingest (URL, fichiers, GDrive en option), écrit dans Chroma.
* **UI (Streamlit)**: requête sémantique, affiche top-k + sources/métadonnées.
* **n8n (optionnel)**: planifications (GDrive, URLs) + import/export de workflows.

## API Ingestor

`POST /ingest` JSON:

```json
{
  "source": "https://example.com/page",
  "source_type": "url",
  "hints": {"matiere": "NSI", "niveau": "terminale"}
}
```

Réponse:

```json
{"status": "ok", "added": 1, "skipped": 0}
```

`GET /health` → `{"status": "healthy"}` (latence ciblée <100 ms).

### Paramètres et limites

- Authentification par header `X-API-Token` (obligatoire si configuré) + allowlist CIDR.
- Taille maxi téléchargement distant: `MAX_REMOTE_BYTES` (par défaut 10 MiB).
- Chunking: `INGEST_CHUNK_SIZE=800`, `INGEST_CHUNK_OVERLAP=120` (
  compromis rappel/latence sur VPS). Ajustables via variables d’environnement.
- Embeddings: `OLLAMA_URL` + `OLLAMA_REQUEST_TIMEOUT` (par défaut 60 s) + gestion d'erreurs explicite.
- Insertion Chroma: `CHROMA_HOST`, `CHROMA_PORT`, `CHROMA_REQUEST_TIMEOUT` (30 s par défaut).

## Chroma v2

* Tenant/db par défaut: `default_tenant` / `default_database`
* Nom de collection: `ressources_pedagogiques_terminale` (par défaut côté ingestor)
* Interro via client HTTP: `list_collections`, `get_or_create_collection().query(...)`

### Recherche

- `k` par défaut 4 (UI) avec maximum 8.
- Résultats renvoient `documents`, `metadatas`, `distances`.
- Ajuster `k` via variable `UI_MAX_K` ou paramètre direct dans client Chroma.

## Sécurité & Ops

* Nginx + TLS (Let’s Encrypt), headers de sécurité.
* n8n derrière BasicAuth + clé d’encryption.
* Backups volumes (Chroma/Ollama/n8n), rotation.

## Déploiement VPS — résumé

1. Remplir `infra/.env` (domaines, ports loopback, modèles).
2. `docker compose -f infra/docker-compose.yml --env-file infra/.env up -d`
3. Générer vhosts Nginx depuis `infra/nginx/*.template`, recharger Nginx.
4. Lancer `certbot --nginx` pour TLS et redirections 80→443.
