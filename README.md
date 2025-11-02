# RAG – Export (pour GitHub)
[![CI](https://github.com/cyranoaladin/rag-local/actions/workflows/ci.yml/badge.svg)](https://github.com/cyranoaladin/rag-local/actions/workflows/ci.yml)
- `infra/` : docker-compose, .env.example (sanitisé), vhosts Nginx
- `n8n/`   : workflows JSON, snapshot DB sqlite, webhooks dump
- `src/ingestor/` : FastAPI (si extrait)
- `src/ui/`       : Streamlit (si extrait)
- `ollama-tags.json`, `chroma-heartbeat.http`

### Démarrer en local (dev)

```bash
python -m venv .venv && source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt

cp infra/.env.example infra/.env
# Adapter au besoin : INGESTOR_API_TOKEN, ports loopback, modèles Ollama…

make compose-up        # démarre docker-compose (base + dev override)
make logs              # optionnel, suivi des journaux

bash infra/scripts/smoke.sh  # health + ingestion factice

# Arrêter la stack
make compose-down
```

Outils de contrôle qualité : `make lint`, `make typecheck`, `make test`, `make smoke`.

## Observability & CI
- Endpoint Prometheus `GET /metrics` (ingestor) activé via `METRICS_ENABLED=true` (désactivé par défaut). Voir `docs/observability.md`.
- Métriques : `ingestor_ingests_total{source,modality,status}` et histogramme `ingestor_ingest_duration_seconds` (buckets adaptés VPS).
- Qualité locale : `make lint`, `make typecheck`, `make test`, ou `make ci-local` pour enchaîner les trois.
- Pipeline GitHub Actions (`.github/workflows/ci.yml`) déclenche lint, mypy, pytest (Py 3.10 / 3.11) + artefacts `ruff.txt` / `pytest.xml`.
- Job optionnel `smoke-compose` via `workflow_dispatch` pour bâtir le profil multimodal et exécuter `infra/scripts/smoke.sh`.

## Contrat des métriques (Prometheus)

Le service `ingestor` expose ses métriques via `src/ingestor/metrics.py`. Points clés :

- `METRICS_ENABLED=true` active l'exposition. Hors production, passez à `false` pour désactiver totalement `GET /metrics` (retourne `404`).
- `METRICS_NAMESPACE` permet de préfixer les compteurs (`ingestor_ingests_total`, histogramme `ingestor_ingest_duration_seconds`).
- La batterie de tests (`tests/test_metrics_gating.py`, `tests/test_metrics.py`, `tests/test_metrics_registry_singleton.py`) garantit le contrat 200/404 et l'unicité du registre.
- Pour l'observabilité locale : profil Compose `obs` (`make obs-up`) qui démarre Prometheus + exporter, puis `make obs-quickcheck` pour valider `GET /metrics`.

Commandes utiles :

```bash
make lint && make typecheck && make test
COMPOSE_PROFILES=db,llm,api,obs docker compose -f infra/docker-compose.yml -f infra/docker-compose.obs.yml --env-file infra/.env up -d --build
curl -s http://127.0.0.1:18001/metrics | head -n 20   # enabled
docker compose -f infra/docker-compose.yml -f infra/docker-compose.obs.yml --env-file infra/.env stop ingestor
METRICS_ENABLED=false docker compose -f infra/docker-compose.yml -f infra/docker-compose.obs.yml --env-file infra/.env up -d ingestor
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:18001/metrics  # attendu: 404
```

## Nginx (web) service
- Service profilé: `web` (activé via `COMPOSE_PROFILES`)
- Prod: pas d'exposition de ports (interne au réseau Docker), à exposer via reverse proxy amont
- Dev: ports loopback dans `infra/docker-compose.dev.yml` (80 -> 18080)
- Templates vhost: `infra/nginx/rag-ui.conf.template`, `infra/nginx/rag-n8n.conf.template` rendus dans `infra/nginx/rendered/`

Commandes utiles:

```bash
# Préparer l'env
grep -q '^COMPOSE_PROFILES=' infra/.env || cp infra/.env.example infra/.env

# Rendre et démarrer Nginx
make nginx-up

# Vérifs réseau docker + hôte
docker compose -f infra/docker-compose.yml --env-file infra/.env ps web || true
make nginx-smoke

# Recharger la config sans redémarrer
make nginx-reload

# Arrêt du seul service Nginx
make nginx-down
```
