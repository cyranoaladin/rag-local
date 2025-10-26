# rag-local — Déploiement Production (VPS)

Ce projet fournit un **RAG 100% local** (LLM & embeddings via **Ollama**) avec **ingestion multi-sources**, **UI de recherche**, et **automatisations n8n**, prêt à exposer en **HTTPS** via **Nginx + Let's Encrypt**, sans clés API externes.

## Prérequis VPS
- Ubuntu 22.04/24.04, accès sudo, ports 80/443 ouverts, DNS des domaines pointés sur le VPS.
- Docker + Compose plugin.
- Cloner le repo et copier `infra/.env.example` vers `infra/.env`, puis éditer `RAG_EXTERNAL_DOMAIN`, `N8N_EXTERNAL_DOMAIN`, mots de passe n8n, etc.

## Démarrage (services internes, non exposés)
```bash
docker compose -f infra/docker-compose.yml --env-file infra/.env up -d
docker compose -f infra/docker-compose.yml ps
```

## Exposition HTTPS (Nginx + Certbot)

* Utiliser `infra/nginx/*.template` avec `envsubst` pour générer les vhosts.
* `certbot --nginx -d <domaines> --agree-tos -m <email> --redirect -n`
* Les templates intègrent des headers de sécurité (HSTS, CSP, etc.).

## Ingestion

* Endpoint `POST /ingest` (service **ingestor**) pour URL/fichiers/Google Drive (via n8n ou via API).
* Les chunks et métadonnées sont stockés dans **Chroma** (v2).

## UI

* Streamlit: recherche, top-k, sources, métadonnées.

## Sauvegardes (idée)

* Volume Chroma en snapshot (rsync / restic / rclone) + rotation (daily/weekly).

Voir `SPEC.md` pour l’architecture et le contrat d’API.
