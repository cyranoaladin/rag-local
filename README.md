# RAG – Export (pour GitHub)
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
