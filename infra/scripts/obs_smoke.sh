#!/usr/bin/env bash
set -Eeuo pipefail
echo "[obs] Checking Prometheus health..."
curl -fsS http://127.0.0.1:9090/-/healthy >/dev/null && echo "Prometheus healthy"
echo "[obs] Checking ingest metrics sample..."
curl -fsS "http://127.0.0.1:9090/api/v1/label/__name__/values" | grep -E "ingestor_" && echo "Labels OK" || echo "Labels missing (may need traffic)"
