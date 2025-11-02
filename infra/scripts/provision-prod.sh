#!/usr/bin/env bash
set -euo pipefail

log() {
  printf '[rag-local] %s\n' "$1"
}

require_root() {
  if [ "${EUID}" -ne 0 ]; then
    echo "This script must run as root (try sudo)." >&2
    exit 1
  fi
}

check_ubuntu() {
  if [ ! -f /etc/os-release ]; then
    echo "Cannot detect OS (missing /etc/os-release)." >&2
    exit 1
  fi
  . /etc/os-release
  case "${ID}-${VERSION_ID}" in
    ubuntu-22.*|ubuntu-24.*)
      ;;
    *)
      printf 'Unsupported distribution: %s %s (expected Ubuntu 22.04/24.04).\n' "${NAME}" "${VERSION_ID}" >&2
      exit 1
      ;;
  esac
  UBUNTU_CODENAME="${VERSION_CODENAME}"
}

prompt_value() {
  local prompt="$1"
  local default="${2:-}"
  local value
  while true; do
    if [ -n "${default}" ]; then
      read -r -p "${prompt} [${default}]: " value
      value=${value:-${default}}
    else
      read -r -p "${prompt}: " value
    fi
    if [ -n "${value}" ]; then
      printf '%s' "${value}"
      return 0
    fi
    echo "A value is required." >&2
  done
}

generate_hex() {
  local bytes="$1"
  openssl rand -hex "${bytes}" | tr '[:upper:]' '[:lower:]'
}

install_base_packages() {
  log "Installing base packages"
  apt-get update -y
  apt-get install -y \ 
    ca-certificates \ 
    curl \ 
    gnupg \ 
    lsb-release \ 
    git \ 
    nginx \ 
    certbot \ 
    python3-certbot-nginx \ 
    apache2-utils \ 
    jq \ 
    gettext-base \ 
    openssl
  systemctl enable --now nginx
}

install_docker() {
  if command -v docker >/dev/null 2>&1; then
    log "Docker already present"
    return
  fi
  log "Installing Docker Engine"
  install -m 0755 -d /etc/apt/keyrings
  if [ ! -f /etc/apt/keyrings/docker.gpg ]; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
  fi
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu %s stable\n' \
    "$(dpkg --print-architecture)" "${UBUNTU_CODENAME}" > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
}

add_user_to_docker_group() {
  local target_user="${SUDO_USER:-}"
  if [ -z "${target_user}" ] || [ "${target_user}" = "root" ]; then
    return
  fi
  if id -nG "${target_user}" | tr ' ' '\n' | grep -qx docker; then
    return
  fi
  log "Adding ${target_user} to docker group"
  usermod -aG docker "${target_user}"
}

clone_repository() {
  local repo_url="$1"
  local target_dir="$2"
  local ref="$3"
  if [ -d "${target_dir}/.git" ]; then
    log "Updating existing repository at ${target_dir}"
    git -C "${target_dir}" fetch --tags --force origin
    git -C "${target_dir}" checkout "${ref}"
    git -C "${target_dir}" pull --ff-only origin "${ref}"
  else
    log "Cloning ${repo_url} into ${target_dir}"
    rm -rf "${target_dir}"
    git clone --branch "${ref}" --depth 1 "${repo_url}" "${target_dir}"
  fi
}

write_env_file() {
  local env_file="$1"
  shift
  local lines=("$@")
  umask 177
  {
    printf '# rag-local production environment\n'
    printf '# generated on %s\n\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    for line in "${lines[@]}"; do
      printf '%s\n' "${line}"
    done
  } > "${env_file}"
}

render_nginx() {
  local repo_dir="$1"
  pushd "${repo_dir}/infra" >/dev/null
  mkdir -p nginx/rendered
  set -a
  . ./.env
  set +a
  envsubst < nginx/rag-ui.conf.template > nginx/rendered/rag-ui.conf
  envsubst < nginx/rag-n8n.conf.template > nginx/rendered/rag-n8n.conf
  popd >/dev/null
}

deploy_nginx_configs() {
  local repo_dir="$1"
  install -d -m 0755 /etc/nginx/sites-available /etc/nginx/sites-enabled /var/www/html
  cp "${repo_dir}/infra/nginx/rendered"/rag-ui.conf /etc/nginx/sites-available/rag-ui.conf
  cp "${repo_dir}/infra/nginx/rendered"/rag-n8n.conf /etc/nginx/sites-available/rag-n8n.conf
  ln -sf /etc/nginx/sites-available/rag-ui.conf /etc/nginx/sites-enabled/rag-ui.conf
  ln -sf /etc/nginx/sites-available/rag-n8n.conf /etc/nginx/sites-enabled/rag-n8n.conf
  nginx -t
  systemctl reload nginx
}

run_compose_stack() {
  local repo_dir="$1"
  pushd "${repo_dir}/infra" >/dev/null
  docker compose -f docker-compose.yml --env-file .env pull
  docker compose -f docker-compose.yml --env-file .env up -d --build
  popd >/dev/null
}

preload_ollama_models() {
  local repo_dir="$1"
  log "Preloading Ollama models"
  ( cd "${repo_dir}/infra/scripts" && COMPOSE_PROFILES="db,llm,api" ./ollama-preload.sh )
}

run_certbot() {
  local email="$1"
  shift
  local domains=("$@")
  if [ "${#domains[@]}" -eq 0 ]; then
    return
  fi
  local args=(--nginx --non-interactive --agree-tos --redirect -m "${email}")
  for domain in "${domains[@]}"; do
    args+=(-d "${domain}")
  done
  log "Requesting TLS certificates via Certbot"
  certbot "${args[@]}"
  nginx -t
  systemctl reload nginx
}

require_root
check_ubuntu
install_base_packages
install_docker
add_user_to_docker_group

GIT_REPO=${GIT_REPO:-https://github.com/cyranoaladin/rag-local.git}
INSTALL_DIR=${INSTALL_DIR:-/opt/rag-local}
GIT_REF=${GIT_REF:-main}
TIMEZONE=${TIMEZONE:-Europe/Paris}
DEFAULT_N8N_USER=${DEFAULT_N8N_USER:-admin}

log "Collecting deployment parameters"
RAG_DOMAIN=$(prompt_value "Streamlit domain (e.g. rag.example.com)")
DEFAULT_N8N_DOMAIN=""
if [[ "${RAG_DOMAIN}" == *.* ]]; then
  rest_part="${RAG_DOMAIN#*.}"
  if [ -n "${rest_part}" ] && [ "${rest_part}" != "${RAG_DOMAIN}" ]; then
    DEFAULT_N8N_DOMAIN="rag-n8n.${rest_part}"
  fi
fi
N8N_DOMAIN=$(prompt_value "n8n domain (e.g. automations.example.com)" "${DEFAULT_N8N_DOMAIN}")
CERTBOT_EMAIL=$(prompt_value "Email for Let's Encrypt notifications")
ALLOWLIST_DEFAULT="127.0.0.1/32,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
INGEST_ALLOWLIST=$(prompt_value "CIDR allowlist for ingestor" "${ALLOWLIST_DEFAULT}")
read -r -p "Enable Basic Auth on Streamlit UI? [y/N]: " enable_ui_auth
enable_ui_auth=${enable_ui_auth,,}
UI_AUTH_USER=""
UI_AUTH_PASSWORD=""
if [[ "${enable_ui_auth}" =~ ^(y|yes)$ ]]; then
  UI_AUTH_USER=$(prompt_value "Streamlit Basic Auth user" "admin")
  while true; do
    read -r -s -p "Streamlit Basic Auth password: " pwd1
    echo
    read -r -s -p "Confirm Streamlit Basic Auth password: " pwd2
    echo
    if [ -n "${pwd1}" ] && [ "${pwd1}" = "${pwd2}" ]; then
      UI_AUTH_PASSWORD="${pwd1}"
      break
    fi
    echo "Passwords do not match or are empty. Try again." >&2
  done
fi
N8N_USER=$(prompt_value "n8n Basic Auth user" "${DEFAULT_N8N_USER}")
read -r -p "n8n Basic Auth password (leave blank to auto-generate): " N8N_PASS_INPUT
if [ -n "${N8N_PASS_INPUT}" ]; then
  N8N_PASSWORD="${N8N_PASS_INPUT}"
else
  N8N_PASSWORD=$(generate_hex 16)
fi

log "Generating secrets"
INGESTOR_API_TOKEN=$(generate_hex 32)
INGEST_AUTH_TOKEN=$(generate_hex 32)
N8N_ENCRYPTION_KEY=$(generate_hex 32)
PROM_USER="prom_user"
PROM_PASS=$(generate_hex 16)

UI_BASIC_AUTH_DIRECTIVE=""
UI_BASIC_AUTH_USER_FILE_DIRECTIVE=""
if [ -n "${UI_AUTH_USER}" ]; then
  UI_BASIC_AUTH_DIRECTIVE='auth_basic "Streamlit";'
  UI_BASIC_AUTH_USER_FILE_DIRECTIVE='auth_basic_user_file /etc/nginx/.htpasswd-rag-ui;'
fi

ENV_FILE="${INSTALL_DIR}/infra/.env"
clone_repository "${GIT_REPO}" "${INSTALL_DIR}" "${GIT_REF}"
mkdir -p "${INSTALL_DIR}/infra/nginx/rendered" "${INSTALL_DIR}/infra/data/uploads" "${INSTALL_DIR}/infra/creds"

if [ -n "${UI_AUTH_USER}" ]; then
  log "Creating Streamlit Basic Auth file"
  htpasswd -bc /etc/nginx/.htpasswd-rag-ui "${UI_AUTH_USER}" "${UI_AUTH_PASSWORD}"
fi

ENV_LINES=(
  "RAG_EXTERNAL_DOMAIN=$(printf '%q' "${RAG_DOMAIN}")"
  "N8N_EXTERNAL_DOMAIN=$(printf '%q' "${N8N_DOMAIN}")"
  "TZ=$(printf '%q' "${TIMEZONE}")"
  "INGESTOR_API_TOKEN=$(printf '%q' "${INGESTOR_API_TOKEN}")"
  "INGEST_AUTH_TOKEN=$(printf '%q' "${INGEST_AUTH_TOKEN}")"
  "N8N_ENCRYPTION_KEY=$(printf '%q' "${N8N_ENCRYPTION_KEY}")"
  "N8N_BASIC_AUTH_USER=$(printf '%q' "${N8N_USER}")"
  "N8N_BASIC_AUTH_PASSWORD=$(printf '%q' "${N8N_PASSWORD}")"
  "UI_BASIC_AUTH_USER_FILE_DIRECTIVE=$(printf '%q' "${UI_BASIC_AUTH_USER_FILE_DIRECTIVE}")"
  "UI_BASIC_AUTH_DIRECTIVE=$(printf '%q' "${UI_BASIC_AUTH_DIRECTIVE}")"
  "COMPOSE_PROFILES=$(printf '%q' "db,llm,api,ui,automations,web")"
  "CHROMA_PORT=8000"
  "OLLAMA_PORT=11434"
  "N8N_PORT=5678"
  "STREAMLIT_PORT=8501"
  "INGESTOR_PORT=8001"
  "NGINX_N8N_PORT=15678"
  "NGINX_UI_PORT=18501"
  "NGINX_CLIENT_MAX_BODY_SIZE=$(printf '%q' "32m")"
  "NGINX_UI_UPSTREAM=$(printf '%q' "ui:8501")"
  "NGINX_N8N_UPSTREAM=$(printf '%q' "n8n:5678")"
  "EMBED_MODEL=$(printf '%q' "nomic-embed-text")"
  "SMALL_LLM=$(printf '%q' "llama3.2:latest")"
  "INGEST_BASE_URL=$(printf '%q' "http://ingestor:8001")"
  "INGEST_AUTH_HEADER=$(printf '%q' "X-API-Token")"
  "INGESTOR_IP_ALLOWLIST=$(printf '%q' "${INGEST_ALLOWLIST}")"
  "INGEST_CHUNK_SIZE=800"
  "INGEST_CHUNK_OVERLAP=120"
  "MAX_REMOTE_BYTES=26214400"
  "METRICS_ENABLED=true"
  "METRICS_NAMESPACE=$(printf '%q' "rag_local")"
  "CHROMA_REQUEST_TIMEOUT=30"
  "OLLAMA_REQUEST_TIMEOUT=60"
  "INGEST_API_BASE=$(printf '%q' "http://ingestor:8001")"
  "INGEST_API_TOKEN=$(printf '%q' "${INGESTOR_API_TOKEN}")"
  "UI_DEFAULT_K=4"
  "UI_MAX_K=8"
  "UI_WEBHOOK_TIMEOUT=10"
  "UI_CHROMA_TIMEOUT=30"
  "N8N_DEFAULT_WEBHOOK=$(printf '%q' "https://${N8N_DOMAIN}/webhook/rag-ingest")"
  "MULTIMODAL_ENABLED=false"
  "MM_PARSER_TIMEOUT=30"
  "MM_MAX_CHARS_PER_CHUNK=1200"
  "MM_CACHE_DIR=$(printf '%q' "/data/mm-cache")"
  "PROMETHEUS_SCRAPE_USER=$(printf '%q' "${PROM_USER}")"
  "PROMETHEUS_SCRAPE_PASSWORD=$(printf '%q' "${PROM_PASS}")"
  "LOCAL_SOURCE_ROOT=$(printf '%q' "/data/uploads")"
)

log "Writing infra/.env"
write_env_file "${ENV_FILE}" "${ENV_LINES[@]}"
chmod 600 "${ENV_FILE}"

render_nginx "${INSTALL_DIR}"
deploy_nginx_configs "${INSTALL_DIR}"
run_compose_stack "${INSTALL_DIR}"
preload_ollama_models "${INSTALL_DIR}"
run_certbot "${CERTBOT_EMAIL}" "${RAG_DOMAIN}" "${N8N_DOMAIN}"

log "Stack status"
docker compose -f "${INSTALL_DIR}/infra/docker-compose.yml" --env-file "${ENV_FILE}" ps

cat <<INFO

Deployment completed.
Repository path : ${INSTALL_DIR}
Environment file: ${ENV_FILE}

Important credentials:
  - INGESTOR_API_TOKEN: ${INGESTOR_API_TOKEN}
  - INGEST_AUTH_TOKEN : ${INGEST_AUTH_TOKEN}
  - n8n user/password : ${N8N_USER} / ${N8N_PASSWORD}
  - Prometheus scrape : ${PROM_USER} / ${PROM_PASS}
$(if [ -n "${UI_AUTH_USER}" ]; then printf '  - Streamlit Basic Auth: %s / %s\n' "${UI_AUTH_USER}" "${UI_AUTH_PASSWORD}"; fi)

Next steps:
  - Validate https://${RAG_DOMAIN} is reachable.
  - Validate https://${N8N_DOMAIN} (n8n) responds with Basic Auth.
  - Optionally run ${INSTALL_DIR}/infra/scripts/smoke.sh for additional checks.

INFO
