#!/usr/bin/env bash
set -euo pipefail

info() {
  echo "[INFO] $1"
}

warn() {
  echo "[WARN] $1" >&2
}

die() {
  echo "[ERROR] $1" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Commande requise introuvable : $1"
}

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${TARGET_DIR:-/srv/rag}"
BACKUP_ROOT="${BACKUP_ROOT:-/srv/rag-backups}"
COMPOSE_SRC="${COMPOSE_SRC:-$PROJECT_ROOT/infra/docker-compose.prod.yml}"
OVERRIDE_SRC="${OVERRIDE_SRC:-$PROJECT_ROOT/infra/docker-compose.override.prod.yml}"
ENV_FILE="${ENV_FILE:-$TARGET_DIR/.env}"
GDRIVE_SECRET="${GDRIVE_SECRET:-$TARGET_DIR/creds/gdrive-service-account.json}"
HTPASSWD_SOURCE="${HTPASSWD_SOURCE:-}"
HTPASSWD_TARGET="${HTPASSWD_TARGET:-/etc/nginx/.htpasswd-n8n}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

[[ $EUID -eq 0 ]] || die "Exécuter ce script en root (sudo)."

for bin in docker git rsync tar; do
  require_cmd "$bin"
done

[[ -f "$COMPOSE_SRC" ]] || die "Fichier docker-compose source introuvable : $COMPOSE_SRC"

info "Préparation du répertoire cible $TARGET_DIR"
mkdir -p "$TARGET_DIR/creds" "$TARGET_DIR/ingestor" "$TARGET_DIR/ui"

if [[ -n $(ls -A "$TARGET_DIR" 2>/dev/null) ]]; then
  info "Sauvegarde des fichiers existants"
  mkdir -p "$BACKUP_ROOT"
  BACKUP_DIR="$BACKUP_ROOT/$TIMESTAMP"
  mkdir -p "$BACKUP_DIR"
  for item in docker-compose.yml docker-compose.override.yml .env; do
    if [[ -f "$TARGET_DIR/$item" ]]; then
      cp "$TARGET_DIR/$item" "$BACKUP_DIR/" || warn "Impossible de sauvegarder $item"
    fi
  done
  if [[ -d "$TARGET_DIR/ingestor" ]]; then
    tar -czf "$BACKUP_DIR/ingestor.tgz" -C "$TARGET_DIR" ingestor || warn "Sauvegarde ingestor incomplète"
  fi
  if [[ -d "$TARGET_DIR/ui" ]]; then
    tar -czf "$BACKUP_DIR/ui.tgz" -C "$TARGET_DIR" ui || warn "Sauvegarde ui incomplète"
  fi
  info "Sauvegarde réalisée dans $BACKUP_DIR"
fi

info "Synchronisation des sources applicatives"
rsync -a --delete "$PROJECT_ROOT/src/ingestor/" "$TARGET_DIR/ingestor/"
rsync -a --delete "$PROJECT_ROOT/src/ui/" "$TARGET_DIR/ui/"

info "Déploiement des fichiers Compose"
install -m 640 "$COMPOSE_SRC" "$TARGET_DIR/docker-compose.yml"
if [[ -f "$OVERRIDE_SRC" ]]; then
  install -m 640 "$OVERRIDE_SRC" "$TARGET_DIR/docker-compose.override.yml"
else
  warn "Aucun override Compose fourni"
fi

[[ -f "$ENV_FILE" ]] || die "Fichier .env absent : $ENV_FILE"
[[ -s "$ENV_FILE" ]] || die ".env est vide : $ENV_FILE"
[[ -f "$GDRIVE_SECRET" ]] || die "Clé Google Drive manquante : $GDRIVE_SECRET"

if [[ -n "$HTPASSWD_SOURCE" ]]; then
  info "Mise à jour de l'empreinte htpasswd"
  install -m 640 "$HTPASSWD_SOURCE" "$HTPASSWD_TARGET"
fi
[[ -f "$HTPASSWD_TARGET" ]] || warn ".htpasswd Nginx introuvable ($HTPASSWD_TARGET). Vérifiez la protection n8n."

info "Validation de la configuration Compose"
(
  cd "$TARGET_DIR"
  docker compose config >/dev/null
)

info "Mise à jour des images tierces"
(
  cd "$TARGET_DIR"
  docker compose pull chroma ollama n8n
)

info "Construction des images internes"
(
  cd "$TARGET_DIR"
  docker compose build --pull ingestor ui
)

info "Relance des services"
(
  cd "$TARGET_DIR"
  docker compose up -d --remove-orphans
)

if command -v nginx >/dev/null 2>&1; then
  info "Validation Nginx"
  if nginx -t >/dev/null 2>&1; then
    systemctl reload nginx || warn "Échec reload Nginx"
  else
    warn "Configuration Nginx invalide, rechargement ignoré"
  fi
else
  warn "Nginx non détecté, étape de reload ignorée"
fi

info "Préchargement des modèles Ollama"
(
  set -o allexport
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +o allexport
  MODELS=()
  [[ -n "${EMBED_MODEL:-}" ]] && MODELS+=("$EMBED_MODEL")
  [[ -n "${SMALL_LLM:-}" ]] && MODELS+=("$SMALL_LLM")
  if [[ ${#MODELS[@]} -gt 0 ]]; then
    OLLAMA_ID=$(cd "$TARGET_DIR" && docker compose ps -q ollama || true)
    if [[ -n "$OLLAMA_ID" ]]; then
      for model in "${MODELS[@]}"; do
        info "  → ollama pull $model"
        docker exec "$OLLAMA_ID" ollama pull "$model" || warn "Impossible de précharger $model"
      done
    else
      warn "Service ollama introuvable pour le préchargement"
    fi
  else
    warn "Aucun modèle Ollama défini dans .env"
  fi
)

info "État final des services"
(
  cd "$TARGET_DIR"
  docker compose ps
)

info "Déploiement terminé"
