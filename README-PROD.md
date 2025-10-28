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

| Route | Méthode | Payload | Notes |
|-------|---------|---------|-------|
| `/ingest` | `POST` | `multipart/form-data` (`file`), query `mode=text|multimodal` | MIME whitelist (`application/pdf`, `image/png`, `image/jpeg`). Timeout parse (`MM_PARSER_TIMEOUT`) → fallback texte si dépassement. |
| `/ingest/source` | `POST` | JSON (`source`, `source_type`, `hints`) | Compatibilité n8n / ingestion indirecte (URL, GDrive, DOCX/PPTX montés localement). |
| `/health` | `GET` | — | Probe compose/Nginx |

* Multimodal → RAG-Anything (PDF/PNG/JPG), chunks typés (`metadata.modality`), cache `/data/cache`.
* Text mode → fallback rapide (PyPDFLoader, DOCX) ; n8n reste inchangé.
* `infra/scripts/smoke.sh` : curl PNG + PDF (attendu `modalities.image >= 1`, `modalities.text >= 1`).

```bash
INGESTOR_API_TOKEN=changeme ./infra/scripts/smoke.sh
```
* Variables clés : `MULTIMODAL_ENABLED`, `MM_CACHE_DIR`, `MM_PARSER_TIMEOUT`, `INGEST_MAX_FILE_MB`, `MM_MAX_CHARS_PER_CHUNK`, `MULTIMODAL_DEPS` (`=1` uniquement pour les builds réalisés avec le profil `multimodal`).

## UI

* Streamlit: recherche, top-k, sources, métadonnées.

## Sauvegardes (idée)

* Volume Chroma en snapshot (rsync / restic / rclone) + rotation (daily/weekly).

Voir `SPEC.md` pour l’architecture et le contrat d’API.
