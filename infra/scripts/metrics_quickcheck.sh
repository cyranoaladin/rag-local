#!/usr/bin/env bash
set -Eeuo pipefail

PROM_URL="${PROM_URL:-http://127.0.0.1:19090}"
TARGET_URL="${TARGET_URL:-http://127.0.0.1:18001/metrics}"

echo "== Quickcheck Prometheus =="
curl -fsS "${PROM_URL}/-/ready" && echo "PROM: ready OK" || { echo "PROM: ready FAIL"; exit 1; }
curl -fsS "${PROM_URL}/-/healthy" && echo "PROM: healthy OK" || { echo "PROM: healthy FAIL"; exit 1; }

echo -e "\n== Exemple de label (dump limité) =="
curl -fsS "${PROM_URL}/api/v1/labels" | head -c 800 || true
echo

echo -e "\n== Sanity /metrics exposé par ingestor =="
curl -fsS "${TARGET_URL}" | head -n 20 || { echo "Ingestor /metrics indisponible"; exit 1; }

echo -e "\n== Requête simple sur ingest_success_total (peut retourner vide si stack idle) =="
curl -fsS --data-urlencode 'query=ingest_success_total' "${PROM_URL}/api/v1/query" | head -c 400 || true
echo
