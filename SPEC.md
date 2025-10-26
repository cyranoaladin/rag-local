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

## Chroma v2

* Tenant/db par défaut: `default_tenant` / `default_database`
* Nom de collection: `ressources_pedagogiques_terminale` (par défaut côté ingestor)
* Interro via client HTTP: `list_collections`, `get_or_create_collection().query(...)`

## Sécurité & Ops

* Nginx + TLS (Let’s Encrypt), headers de sécurité.
* n8n derrière BasicAuth + clé d’encryption.
* Backups volumes (Chroma/Ollama/n8n), rotation.

## Déploiement VPS — résumé

1. Remplir `infra/.env` (domaines, ports loopback, modèles).
2. `docker compose -f infra/docker-compose.yml --env-file infra/.env up -d`
3. Générer vhosts Nginx depuis `infra/nginx/*.template`, recharger Nginx.
4. Lancer `certbot --nginx` pour TLS et redirections 80→443.
