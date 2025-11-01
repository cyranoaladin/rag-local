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
for attempt in $(seq 1 10); do
  if response=$(curl -fsS "${TARGET_URL}" 2>/dev/null); then
    printf '%s' "${response}" | head -n 20
    break
  fi

  if [ "${attempt}" -eq 10 ]; then
    echo "Ingestor /metrics indisponible"
    exit 1
  fi

  echo "Ingestor metrics indisponible, nouvelle tentative dans 3s (${attempt}/10)"
  sleep 3
done

echo -e "\n== Requête simple sur ingest_success_total (peut retourner vide si stack idle) =="
curl -fsS --data-urlencode 'query=ingest_success_total' "${PROM_URL}/api/v1/query" | head -c 400 || true
echo
