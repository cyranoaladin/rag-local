#!/usr/bin/env bash
set -euo pipefail

# Enable Google Drive for prod deployment (ingestor service)
# - Copies a service account JSON into infra/creds/gdrive-sa.json (if provided)
# - Ensures infra/.env contains GOOGLE_APPLICATION_CREDENTIALS and GOOGLE_DRIVE_TOKEN_PATH
# - Restarts the stack (via systemd if present, otherwise docker compose for ingestor)
#
# Usage:
#   ./infra/scripts/enable-gdrive-prod.sh /path/to/service_account.json
#   ./infra/scripts/enable-gdrive-prod.sh   # if infra/creds/gdrive-sa.json already exists

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "${here}/../.." && pwd)
creds_dir="${repo_root}/infra/creds"
dest_json="${creds_dir}/gdrive-sa.json"
env_file="${repo_root}/infra/.env"
compose_file="${repo_root}/infra/docker-compose.prod.yml"

log() { printf '[enable-gdrive] %s\n' "$*"; }
err() { printf '[enable-gdrive][ERROR] %s\n' "$*" >&2; }

require_file() {
  if [ ! -f "$1" ]; then err "Missing file: $1"; exit 1; fi
}

# 1) Handle service account JSON
src_json="${1:-}"
mkdir -p "${creds_dir}"
if [ -n "${src_json}" ]; then
  require_file "${src_json}"
  log "Installing service account JSON -> ${dest_json}"
  cp -f "${src_json}" "${dest_json}"
  chmod 600 "${dest_json}"
else
  if [ -f "${dest_json}" ]; then
    log "Using existing ${dest_json}"
    chmod 600 "${dest_json}" || true
  else
    err "No service account JSON provided and ${dest_json} is missing."
    err "Provide a JSON key path as argument."
    exit 1
  fi
fi

# 2) Ensure env variables in infra/.env
if [ ! -f "${env_file}" ]; then
  err "Environment file not found: ${env_file}"
  err "Create it from infra/.env.production.sample and try again."
  exit 1
fi

set_env() {
  local var="$1"; shift
  local val="$1"; shift
  if grep -qE "^${var}=" "${env_file}"; then
    sed -i -E "s|^${var}=.*|${var}=${val}|" "${env_file}"
  else
    printf '\n%s=%s\n' "${var}" "${val}" >> "${env_file}"
  fi
}

log "Updating ${env_file}"
set_env GOOGLE_APPLICATION_CREDENTIALS "/creds/gdrive-sa.json"
set_env GOOGLE_DRIVE_TOKEN_PATH "/tmp/google-drive-token.json"

# 3) Restart stack
restart_via_systemd() {
  if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files | grep -q '^rag-local\.service'; then
    log "Restarting systemd unit: rag-local.service"
    sudo systemctl restart rag-local.service
    return 0
  fi
  return 1
}

if ! restart_via_systemd; then
  log "Restarting only the ingestor service via docker compose"
  ( cd "${repo_root}" && docker compose -f "${compose_file}" --env-file "${env_file}" up -d --build ingestor )
fi

log "Google Drive is enabled. Ensure the target Drive folder is shared with the service account email."
log "Test with: curl -H 'Authorization: Bearer $INGESTOR_API_TOKEN' -H 'Content-Type: application/json' \\
     -d '{"source_type":"gdrive_folder","source":"<FOLDER_ID>"}' $RAG_API_BASE/ingest"
