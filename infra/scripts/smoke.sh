#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
ASSET_DIR="${REPO_ROOT}/tests/assets"

BASE_URL="${INGEST_BASE_URL:-http://127.0.0.1:8001}"
TOKEN="${INGESTOR_API_TOKEN:-changeme}"

_png_asset="${ASSET_DIR}/tiny.png"
_pdf_asset="${ASSET_DIR}/sample.pdf"

if [[ ! -f "${_png_asset}" ]]; then
  echo "missing asset: ${_png_asset}" >&2
  exit 1
fi

if [[ ! -f "${_pdf_asset}" ]]; then
  echo "missing asset: ${_pdf_asset}" >&2
  exit 1
fi

echo "[smoke] uploading PNG (${_png_asset})"
png_json=$(curl -fsS \
  -H "X-API-Token: ${TOKEN}" \
  -F "file=@${_png_asset};type=image/png" \
  "${BASE_URL}/ingest?mode=multimodal")

python - "$png_json" <<'PY'
import json, sys

data = json.loads(sys.argv[1])
if data.get("status") != "ok":
    raise SystemExit("PNG ingest failed: status != ok")
if data.get("modalities", {}).get("image", 0) < 1:
    raise SystemExit("PNG ingest missing image modality")
print("[smoke] png ingestion ok", data)
PY

echo "[smoke] uploading PDF (${_pdf_asset})"
pdf_json=$(curl -fsS \
  -H "X-API-Token: ${TOKEN}" \
  -F "file=@${_pdf_asset};type=application/pdf" \
  "${BASE_URL}/ingest?mode=multimodal")

python - "$pdf_json" <<'PY'
import json, sys

data = json.loads(sys.argv[1])
if data.get("status") != "ok":
    raise SystemExit("PDF ingest failed: status != ok")
if data.get("modalities", {}).get("text", 0) < 1:
    raise SystemExit("PDF ingest missing text modality")
print("[smoke] pdf ingestion ok", data)
PY

echo "[smoke] checks passed"
