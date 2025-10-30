#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# 1) Récupère le token depuis infra/.env si dispo
TOKEN="${INGESTOR_API_TOKEN:-}"
if [ -z "${TOKEN:-}" ] && [ -f infra/.env ]; then
  TOKEN="$(grep -E '^INGESTOR_API_TOKEN=' infra/.env | sed 's/INGESTOR_API_TOKEN=//' || true)"
fi
[ -n "${TOKEN:-}" ] || { echo "[err] INGESTOR_API_TOKEN manquant (set env ou infra/.env)"; exit 1; }

# 2) Démarre stack dev s’il le faut
docker compose -f infra/docker-compose.yml -f infra/docker-compose.dev.yml up -d

# 3) Attente santé
echo "== wait: health =="
for svc in ingestor ui; do
  for i in {1..30}; do
    st="$(docker inspect "infra-${svc}-1" --format '{{.State.Health.Status}}' 2>/dev/null || echo "starting")"
    echo " - $svc: $st"
    [ "$st" = "healthy" ] && break || sleep 2
  done
done

# 4) Checks externes (host)
curl -fsS http://127.0.0.1:18501/ -o /dev/null && echo "ui(localhost:18501)/ -> OK"
curl -fsS http://127.0.0.1:18001/health -H "X-API-Token: $TOKEN" -o /dev/null && echo "ingestor(localhost:18001)/health -> OK"

# 5) Ingestion smoke
echo "== smoke ingest =="
curl -fsS -X POST "http://127.0.0.1:18001/ingest" \
  -H "Content-Type: application/json" \
  -H "X-API-Token: $TOKEN" \
  -d '{"source_type":"url","source":"https://example.com","hints":{"env":"smoke"}}' | jq -c .

echo "== done =="
