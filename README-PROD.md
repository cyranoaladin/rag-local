# rag-local — Déploiement Production (VPS)

Ce projet fournit un **RAG 100% local** (LLM & embeddings via **Ollama**) avec **ingestion multi-sources**, **UI de recherche**, et **automatisations n8n** (optionnelles). L’architecture est prête à être exposée en **HTTPS** via **Nginx + Let's Encrypt**, sans dépendance à des API externes.

> ℹ️ **Roadmap** — La licence n8n devenant payante, la solution va progressivement converger vers un mode d’ingestion 100 % interne. Ce guide décrit l’état actuel (n8n actif). Un encadré “Transition sans n8n” indique les points d’attention pour préparer sa suppression.

## Prérequis VPS
- Ubuntu 22.04/24.04, accès sudo, ports 80/443 ouverts, DNS des domaines pointés sur le VPS.
- Docker Engine ≥ 24.0 + plugin Compose ≥ 2.24 (`docker compose version`).
- Cloner le repo et copier `infra/.env.example` vers `infra/.env`, puis éditer `RAG_EXTERNAL_DOMAIN`, `N8N_EXTERNAL_DOMAIN` (laisser vide si n8n inactif), les secrets associés, ainsi qu’un `INGEST_AUTH_TOKEN` fort (ex: `openssl rand -hex 32`).

## Secrets à générer
| Nom | Longueur conseillée | Usage | Où le renseigner |
|-----|---------------------|-------|------------------|
| `INGEST_AUTH_TOKEN` | 64 hex (`openssl rand -hex 32`) | Authentifier les appels `/ingest` (UI / n8n) | `infra/.env` (`INGEST_AUTH_TOKEN`) + header UI (`INGEST_AUTH_HEADER`) |
| `INGESTOR_API_TOKEN` | 64 hex | Jeton partagé entre UI et API ingestor | `infra/.env` (`INGESTOR_API_TOKEN`, `INGEST_API_TOKEN`) |
| `N8N_ENCRYPTION_KEY` | 64 hex | Chiffrer les crédentials n8n | `infra/.env` (`N8N_ENCRYPTION_KEY`) |
| `N8N_BASIC_AUTH_PASSWORD` | 32 alphanum | Protège l'UI n8n | `infra/.env` (`N8N_BASIC_AUTH_PASSWORD`) |
| `UI_BASIC_AUTH_USER_FILE_DIRECTIVE` | fichier htpasswd | Optionnel : restreindre Streamlit | `infra/.env` (`UI_BASIC_AUTH_*`) + templates Nginx |
| `PROMETHEUS_SCRAPE_PASSWORD` | 32 alphanum | Restreindre l'accès aux métriques | `infra/.env` (`PROMETHEUS_SCRAPE_*`) |

> Astuce : conserver les secrets hors dépôt (ex: `pass`, `1Password`) et régénérer à chaque rotation.

## Modèles Ollama conseillés
- `EMBED_MODEL=nomic-embed-text` (cohérent avec la collection Chroma)
- `SMALL_LLM=llama3.2:3b` (modèle instruct compact, compatible Ollama 0.3.13)

> Vérifiez les modèles disponibles sur le VPS avec `docker exec "$(docker compose -f /srv/rag/docker-compose.yml ps -q ollama)" ollama list` avant de les déclarer dans `.env`, afin d’éviter un préchargement en échec.

## Démarrage (services internes, non exposés)
```bash
docker compose -f infra/docker-compose.yml --env-file infra/.env up -d
docker compose -f infra/docker-compose.yml ps
```

## Exposition HTTPS (Nginx + Certbot)

* Utiliser `infra/nginx/*.template` avec `envsubst` pour générer les vhosts (les templates n’emploient **pas** `${VAR:-def}`).
* Activer ensuite TLS via `certbot --nginx -d <domaines> --agree-tos -m <email> --redirect -n`.
* Les templates intègrent CSP stricte, `Permissions-Policy`, `X-Frame-Options`, et `Referrer-Policy`.
* Ajouter `add_header Strict-Transport-Security "max-age=63072000" always;` après issuance TLS (HSTS production).

Exemple :
```bash
export RAG_EXTERNAL_DOMAIN="rag.example.com"
export N8N_EXTERNAL_DOMAIN="automations.example.com"
export NGINX_UI_PORT="18501"
export NGINX_N8N_PORT="15678"
export NGINX_CLIENT_MAX_BODY_SIZE="16m"

envsubst < infra/nginx/rag-ui.conf.template  | sudo tee /etc/nginx/sites-available/rag-ui.conf  >/dev/null
envsubst < infra/nginx/rag-n8n.conf.template | sudo tee /etc/nginx/sites-available/rag-n8n.conf >/dev/null
sudo ln -sf /etc/nginx/sites-available/rag-ui.conf  /etc/nginx/sites-enabled/rag-ui.conf
sudo ln -sf /etc/nginx/sites-available/rag-n8n.conf /etc/nginx/sites-enabled/rag-n8n.conf
sudo nginx -t && sudo systemctl reload nginx
```

## Ingestion

* Endpoint `POST /ingest` (service **ingestor**) pour URL/fichiers/Google Drive (via n8n ou via l’onglet “Administration API”).
* Chunking par défaut 800/120 (ajustable via `INGEST_CHUNK_SIZE`, `INGEST_CHUNK_OVERLAP`).
* Les chunks et métadonnées sont stockés dans **Chroma** (v2).

## UI

* Streamlit: recherche, top-k, sources, métadonnées.
* Top-k borné à 8 par défaut (`UI_MAX_K`).
* L’onglet “Via n8n” pré-remplit l’URL du webhook avec la variable `N8N_DEFAULT_WEBHOOK`. En laissant la variable vide, le champ restera à renseigner manuellement (ou pourra être masqué lors de la migration sans n8n).

## Observabilité

* Ingestor expose `GET /metrics` (Prometheus) lorsque `METRICS_ENABLED=true` dans `infra/.env`.
* Mettre à jour la configuration Nginx pour restreindre l'accès `/metrics` à l'allowlist IP interne (cf. documentation sécurité).
* Métriques clés :
	* `ingestor_ingests_total{status}` pour identifier les échecs (`status=http_4xx/http_5xx`).
	* `histogram_quantile` sur `ingestor_ingest_duration_seconds` (p99 > 4s ⇒ alerte latence ingestion).
* Exemple d'alerte PromQL :
	* `sum(increase(ingestor_ingests_total{status!="success"}[5m])) > 0`
	* `histogram_quantile(0.99, sum(rate(ingestor_ingest_duration_seconds_bucket[5m])) by (le)) > 4`

## Sauvegardes (idée)

* Volume Chroma en snapshot (rsync / restic / rclone) + rotation (daily/weekly).

Voir `SPEC.md` pour l’architecture et le contrat d’API.

---
### Transition sans n8n (à préparer)

- Supprimer les profils Compose `automations` et la section `n8n` de `infra/docker-compose.yml` une fois le workflow remplacé.
- Ajuster l’UI Streamlit pour masquer l’onglet “Via n8n” (variables d’environnement à définir : `STREAMLIT_HIDE_N8N_TAB` par exemple).
- Mettre à jour `README`, `SPEC.md` et la documentation d’ingestion pour pointer vers la nouvelle chaîne (ex: script Python ou worker interne).
- Archiver les workflows actuels (`n8n/workflows/examples/`) afin de les traduire dans la solution de remplacement.

## Observability profile (internal-only)
- Set \`METRICS_ENABLED=true\`, bring up Prometheus with \`--profile obs\`
- /metrics is **not** exposed publicly; Prometheus scrapes the ingestor over the bridge network.
