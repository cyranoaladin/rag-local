#!/usr/bin/env bash
set -Eeuo pipefail
# Saas: attend readiness de Prometheus en local (loopback)
for i in {1..20}; do
  if curl -fsS http://127.0.0.1:19090/-/ready >/dev/null 2>&1; then
    echo "Prometheus ready"; break
  fi
  sleep 1
done
# Vérifie présence de la target (ingestor)
curl -fsS "http://127.0.0.1:19090/api/v1/targets" | grep -E '"ingestor:8001"|UP' -A2 || {
  echo "❌ Target ingestor indisponible ou DOWN"; exit 1; }
echo "✅ Scrape target UP"
