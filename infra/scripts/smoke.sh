#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."

# ENV minimaux
grep -q '^INGESTOR_API_TOKEN=' infra/.env || printf '\nINGESTOR_API_TOKEN=devtoken\n' >> infra/.env
grep -q '^INGESTOR_IP_ALLOWLIST=' infra/.env || printf '\nINGESTOR_IP_ALLOWLIST=\n' >> infra/.env

# Démarrage stack (base + dev)
docker compose -f infra/docker-compose.yml -f infra/docker-compose.dev.yml --env-file infra/.env up -d --remove-orphans

# Attente santé (simple boucle)
echo "== wait: health =="
for attempt in $(seq 1 30); do
  ok=1
  docker compose -f infra/docker-compose.yml -f infra/docker-compose.dev.yml ps | grep -q "chroma.*(healthy)"     || ok=0
  docker compose -f infra/docker-compose.yml -f infra/docker-compose.dev.yml ps | grep -q "ollama.*(healthy)"     || ok=0
  docker compose -f infra/docker-compose.yml -f infra/docker-compose.dev.yml ps | grep -q "ingestor.*(healthy)"   || ok=0 || true
  docker compose -f infra/docker-compose.yml -f infra/docker-compose.dev.yml ps | grep -q "ui.*(healthy)"         || ok=0 || true
  if [ "$ok" = "1" ]; then
    break
  fi
  echo "waiting for healthy services (attempt ${attempt}/30)..."
  sleep 2
done

if [ "$ok" != "1" ]; then
  echo "Services failed to reach healthy state" >&2
  exit 1
fi

# Checks côté hôte
curl -fsS http://127.0.0.1:18001/health -H "X-API-Token: ${INGESTOR_API_TOKEN:-devtoken}" -o /dev/null && echo "ingestor: OK"

# Ingestion smoke
curl -fsS -X POST "http://127.0.0.1:18001/ingest" \
  -H "X-API-Token: ${INGESTOR_API_TOKEN:-devtoken}" \
  -H "Content-Type: application/json" \
  -d '{"source_type":"url","source":"https://example.com","hints":{"env":"smoke"}}' \
  | jq -c .

echo "== done =="
