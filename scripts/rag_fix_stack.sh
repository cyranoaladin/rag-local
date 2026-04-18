#!/bin/bash
# rag_fix_stack.sh — Remédiation automatique de la stack RAG (nginx + compose)
# À exécuter sur le VPS (ex: root@mfai:/srv/rag-local)

set -euo pipefail

BASE="/srv/rag-local"
INFRA="$BASE/infra"
ENV_FILE="$INFRA/.env"
ENV_EXAMPLE="$INFRA/.env.example"
TEMPLATES_DIR="$INFRA/nginx"
RENDERED_DIR="$TEMPLATES_DIR/rendered"
COMPOSE_BASE="$INFRA/docker-compose.yml"
COMPOSE_DEV="$INFRA/docker-compose.dev.yml"
COMPOSE_CMD=(docker compose)

log() {
  printf '[%s] %s\n' "$(date +'%Y-%m-%d %H:%M:%S')" "$*"
}

abort() {
  log "ERREUR: $*" >&2
  exit 1
}

require_file() {
  local path="$1"
  local description="$2"
  [ -e "$path" ] || abort "$description manquant: $path"
}

ensure_env_file() {
  if [ ! -f "$ENV_FILE" ]; then
    require_file "$ENV_EXAMPLE" "Fichier d'exemple .env"
    log "Copie du .env example -> .env"
    cp "$ENV_EXAMPLE" "$ENV_FILE"
  fi
}

backup_env_file() {
  local timestamp
  timestamp="$(date +'%Y%m%d_%H%M%S')"
  cp "$ENV_FILE" "$ENV_FILE.bak_${timestamp}"
  log "Sauvegarde de $ENV_FILE dans $ENV_FILE.bak_${timestamp}"
}

# Récupère la première valeur server_name du fichier nginx cible
extract_server_name() {
  local pattern="$1"
  local file
  file=$(ls /etc/nginx/sites-enabled/*"${pattern}"* 2>/dev/null | head -n1 || true)
  if [ -n "$file" ]; then
    grep -E "^[[:space:]]*server_name" "$file" | head -n1 | sed -E 's/.*server_name[[:space:]]+([^; ]+).*/\1/'
  fi
}

# Met à jour / ajoute une variable dans le .env (uniquement si absente ou vide)
ensure_env_var() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" "$ENV_FILE"; then
    local current
    current=$(grep "^${key}=" "$ENV_FILE" | tail -n1 | cut -d'=' -f2-)
    if [ -z "$current" ]; then
      log "Mise à jour $key (valeur vide)"
      sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
    fi
  else
    log "Ajout de $key=${value} dans .env"
    printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  fi
}

# Lecture / préparation des variables critiques pour le rendu Nginx
prepare_env_vars() {
  local rag_domain n8n_domain
  rag_domain="${RAG_EXTERNAL_DOMAIN:-}"
  n8n_domain="${N8N_EXTERNAL_DOMAIN:-}"

  if [ -z "$rag_domain" ]; then
    rag_domain=$(extract_server_name "rag-ui" || true)
  fi
  if [ -z "$rag_domain" ]; then
    rag_domain="rag-ui.example.com"
  fi

  if [ -z "$n8n_domain" ]; then
    n8n_domain=$(extract_server_name "rag-n8n" || true)
  fi
  if [ -z "$n8n_domain" ]; then
    n8n_domain="rag-n8n.example.com"
  fi

  ensure_env_var "RAG_EXTERNAL_DOMAIN" "$rag_domain"
  ensure_env_var "N8N_EXTERNAL_DOMAIN" "$n8n_domain"
  ensure_env_var "NGINX_CLIENT_MAX_BODY_SIZE" "16m"
  ensure_env_var "NGINX_UI_PORT" "18501"
  ensure_env_var "NGINX_N8N_PORT" "15678"
  ensure_env_var "NGINX_UI_UPSTREAM" "ui:8501"
  ensure_env_var "NGINX_N8N_UPSTREAM" "n8n:5678"
  ensure_env_var "UI_BASIC_AUTH_DIRECTIVE" ""
  ensure_env_var "UI_BASIC_AUTH_USER_FILE_DIRECTIVE" ""
  ensure_env_var "N8N_BASIC_AUTH_DIRECTIVE" ""
  ensure_env_var "N8N_BASIC_AUTH_USER_FILE_DIRECTIVE" ""
  ensure_env_var "INGEST_BASE_URL" "http://ingestor:8001"
  ensure_env_var "INGEST_API_TOKEN" "${INGEST_API_TOKEN:-${INGESTOR_API_TOKEN:-__CHANGE_ME__}}"
  ensure_env_var "COMPOSE_PROFILES" "db,llm,api,ui,automations,web"
}

render_nginx_templates() {
  require_file "$TEMPLATES_DIR/rag-ui.conf.template" "Template rag-ui"
  require_file "$TEMPLATES_DIR/rag-n8n.conf.template" "Template rag-n8n"
  mkdir -p "$RENDERED_DIR"
  log "Rendu des templates Nginx"
  ( set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
    envsubst < "$TEMPLATES_DIR/rag-ui.conf.template" > "$RENDERED_DIR/rag-ui.conf"
    envsubst < "$TEMPLATES_DIR/rag-n8n.conf.template" > "$RENDERED_DIR/rag-n8n.conf"
  )
  ls -l "$RENDERED_DIR"/*.conf
}

reload_host_nginx() {
  if command -v nginx >/dev/null 2>&1; then
    log "Test de la configuration Nginx système"
    nginx -t && systemctl reload nginx
  else
    log "Nginx système non présent, étape ignorée"
  fi
}

compose_up() {
  require_file "$COMPOSE_BASE" "docker-compose.yml"
  require_file "$COMPOSE_DEV" "docker-compose.dev.yml"
  log "Démarrage des services (compose + override dev)"
  local compose_cmd
  compose_cmd=(docker compose -f "$COMPOSE_BASE" -f "$COMPOSE_DEV" --env-file "$ENV_FILE")
  local compose_profiles_value
  compose_profiles_value="${COMPOSE_PROFILES:-db,llm,api,ui,automations,web}"
  COMPOSE_PROFILES="$compose_profiles_value" "${compose_cmd[@]}" up -d web ui ingestor n8n
  COMPOSE_PROFILES="$compose_profiles_value" "${compose_cmd[@]}" ps
}

run_health_checks() {
  local ui_port api_port web_port
  ui_port=$(grep '^NGINX_UI_PORT=' "$ENV_FILE" | tail -n1 | cut -d'=' -f2-)
  ui_port=${ui_port:-18501}
  api_port=18001
  web_port=18080

  log "Vérification API (loopback ${api_port})"
  if curl -s -o /dev/null -w 'API /health -> %{http_code}\n' "http://127.0.0.1:${api_port}/health"; then
    :
  else
    log "API non joignable sur ${api_port}"
  fi

  log "Vérification UI directe (${ui_port})"
  if curl -s -o /dev/null -w 'UI direct -> %{http_code}\n' "http://127.0.0.1:${ui_port}"; then
    :
  else
    log "UI non joignable sur ${ui_port}"
  fi

  log "Vérification proxy web (${web_port})"
  if curl -s -o /dev/null -w 'Proxy web -> %{http_code}\n' "http://127.0.0.1:${web_port}"; then
    :
  else
    log "Proxy web non joignable sur ${web_port}"
  fi
}

main() {
  require_file "$BASE" "Répertoire racine du projet"
  ensure_env_file
  backup_env_file
  prepare_env_vars
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
  render_nginx_templates
  reload_host_nginx
  compose_up
  run_health_checks
  log "Remédiation terminée"
}

main "$@"
