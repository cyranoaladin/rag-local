#!/usr/bin/env bash
set -euo pipefail

# Installs/updates the rag-local systemd unit on the host.
# Usage:
#   RAG_DIR=/srv/rag-local ./infra/scripts/install-systemd.sh
# Defaults:
RAG_DIR=${RAG_DIR:-/srv/rag-local}
SERVICE_NAME=rag-local.service
TEMPLATE=infra/systemd/rag-local.service.template

if [ ! -d "$RAG_DIR" ]; then
  echo "RAG_DIR does not exist: $RAG_DIR" >&2
  exit 1
fi
if [ ! -f "$TEMPLATE" ]; then
  echo "Template missing: $TEMPLATE" >&2
  exit 1
fi

# Render service file using envsubst
export RAG_DIR
TMP_FILE=$(mktemp)
trap 'rm -f "$TMP_FILE"' EXIT
if ! command -v envsubst >/dev/null 2>&1; then
  echo "envsubst is required (install gettext-base)" >&2
  exit 1
fi
envsubst < "$TEMPLATE" > "$TMP_FILE"

# Install service
sudo install -m 0644 "$TMP_FILE" "/etc/systemd/system/${SERVICE_NAME}"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl restart "$SERVICE_NAME"

echo "Installed and started systemd unit: ${SERVICE_NAME} (RAG_DIR=$RAG_DIR)"