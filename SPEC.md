# SPEC — rag-local

## Architecture

* **Chroma (DB v2)**: stockage embeddings + métadonnées.
* **Ollama**: embeddings (nomic-embed-text), LLM (llama3.2).
* **Ingestor (FastAPI)**: /health, /ingest (URL, fichiers, GDrive en option), écrit dans Chroma.
* **UI (Streamlit)**: requête sémantique, affiche top-k + sources/métadonnées.
* **n8n (optionnel)**: planifications (GDrive, URLs) + import/export de workflows.

## API Ingestor

| Route | Méthode | Payload | Détails |
|-------|---------|---------|---------|
| `/ingest` | `POST` | `multipart/form-data` (`file`), query `mode=text|multimodal` | MIME whitelist (`application/pdf`, `image/png`, `image/jpeg`). Multimodal → RAG-Anything (timeout `MM_PARSER_TIMEOUT`, fallback texte si dépassement). Résultat : `{"status":"ok","added":N,"skipped":M,"modalities":{...}}`. |
| `/ingest/source` | `POST` | JSON (héritage : `source`, `source_type`, `hints`) | Pipeline historique (URL/GDrive/fichiers locaux, DOCX/PPTX montés). Toujours traité en mode texte. |
| `/health` | `GET` | — | Liveness/Compose. |

## Chroma v2

* Tenant/db par défaut: `default_tenant` / `default_database`
* Nom de collection: `ressources_pedagogiques_terminale` (par défaut côté ingestor)
* Interro via client HTTP: `list_collections`, `get_or_create_collection().query(...)`

## Sécurité & Ops

* Nginx + TLS (Let’s Encrypt), headers de sécurité.
* n8n derrière BasicAuth + clé d’encryption.
* Ingestor : token `X-API-Token` + allowlist IP (env `INGESTOR_API_TOKEN`, `INGEST_IP_ALLOWLIST`).
* Upload : MIME whitelist + limite poids (`INGEST_MAX_FILE_MB`), parsing multimodal time-boxed (env `MM_PARSER_TIMEOUT`).
* Backups volumes (Chroma/Ollama/n8n), rotation.

## Déploiement VPS — résumé

1. Remplir `infra/.env` (domaines, ports loopback, modèles).
2. `docker compose -f infra/docker-compose.yml --env-file infra/.env up -d`
3. Générer vhosts Nginx depuis `infra/nginx/*.template`, recharger Nginx.
4. Lancer `certbot --nginx` pour TLS et redirections 80→443.
5. Activer le profil `multimodal` uniquement si `MULTIMODAL_DEPS=1` (build) et `MULTIMODAL_ENABLED=true` (runtime).
