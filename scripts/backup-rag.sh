#!/usr/bin/env bash
#
# backup-rag.sh — Sauvegarde automatisée de rag-local
# Usage: ./scripts/backup-rag.sh [--full|--incremental] [--restore=PATH]
#
# Auteur : Alaeddine BEN RHOUMA
# Date : Mars 2026
#

set -euo pipefail

# ═══════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Variables d'environnement (peuvent être override)
RAG_DIR="${RAG_DIR:-/srv/rag-local}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/rag-local}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
RETENTION_WEEKLY="${RETENTION_WEEKLY:-12}"
RETENTION_MONTHLY="${RETENTION_MONTHLY:-12}"

# Docker Compose
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-rag-local}"

# Couleurs
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# ═══════════════════════════════════════════════════════════════════
# Logging
# ═══════════════════════════════════════════════════════════════════

log_info() {
    echo -e "${GREEN}[INFO]${NC} $(date '+%Y-%m-%d %H:%M:%S') $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $(date '+%Y-%m-%d %H:%M:%S') $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $(date '+%Y-%m-%d %H:%M:%S') $1"
}

log_debug() {
    echo -e "${BLUE}[DEBUG]${NC} $(date '+%Y-%m-%d %H:%M:%S') $1"
}

# ═══════════════════════════════════════════════════════════════════
# Prérequis
# ═══════════════════════════════════════════════════════════════════

check_dependencies() {
    local missing=()
    
    for cmd in docker docker-compose rsync tar gzip; do
        if ! command -v "$cmd" &> /dev/null; then
            missing+=("$cmd")
        fi
    done
    
    if [ ${#missing[@]} -gt 0 ]; then
        log_error "Dépendances manquantes: ${missing[*]}"
        exit 1
    fi
    
    log_debug "Toutes les dépendances sont installées"
}

check_permissions() {
    if [ "$EUID" -ne 0 ]; then
        log_warn "Ce script devrait être exécuté en tant que root pour accéder aux volumes Docker"
    fi
    
    if [ ! -d "$RAG_DIR" ]; then
        log_error "Répertoire RAG introuvable: $RAG_DIR"
        exit 1
    fi
    
    if [ ! -d "$BACKUP_DIR" ]; then
        log_info "Création du répertoire de sauvegarde: $BACKUP_DIR"
        mkdir -p "$BACKUP_DIR"
    fi
}

# ═══════════════════════════════════════════════════════════════════
# Sauvegarde
# ═══════════════════════════════════════════════════════════════════

backup_volume() {
    local volume_name="$1"
    local backup_type="${2:-full}"
    local timestamp
    timestamp=$(date '+%Y%m%d_%H%M%S')
    local backup_file
    
    log_info "Sauvegarde du volume: $volume_name"
    
    # Nom du fichier de sauvegarde
    if [ "$backup_type" = "full" ]; then
        backup_file="${BACKUP_DIR}/${volume_name}_full_${timestamp}.tar.gz"
    else
        backup_file="${BACKUP_DIR}/${volume_name}_incr_${timestamp}.tar.gz"
    fi
    
    # Sauvegarde avec docker run --rm + tar
    docker run --rm \
        -v "$volume_name":/data:ro \
        -v "$BACKUP_DIR":/backup \
        busybox tar czf "/backup/$(basename "$backup_file")" -C /data .
    
    if [ -f "$backup_file" ]; then
        local size
        size=$(du -h "$backup_file" | cut -f1)
        log_info "✓ Sauvegarde créée: $backup_file ($size)"
    else
        log_error "✗ Échec de la sauvegarde: $backup_file"
        return 1
    fi
}

backup_database() {
    local timestamp
    timestamp=$(date '+%Y%m%d_%H%M%S')
    local backup_file="${BACKUP_DIR}/pgvector_${timestamp}.sql.gz"
    
    log_info "Sauvegarde de la base PostgreSQL (pgvector)"
    
    # Récupérer les variables d'environnement
    local pg_host="${PGVECTOR_HOST:-pgvector}"
    local pg_port="${PGVECTOR_PORT:-5435}"
    local pg_db="${PGVECTOR_DB:-ragdb}"
    local pg_user="${PGVECTOR_USER:-raguser}"
    local pg_password="${PGVECTOR_PASSWORD:-}"
    
    if [ -z "$pg_password" ]; then
        log_warn "PGVECTOR_PASSWORD non défini, tentative sans mot de passe"
    fi
    
    # Sauvegarde avec pg_dump
    PGPASSWORD="$pg_password" docker run --rm \
        --network="${COMPOSE_PROJECT}_rag_net" \
        -e PGPASSWORD="$pg_password" \
        postgres:16-alpine \
        pg_dump -h "$pg_host" -p "$pg_port" -U "$pg_user" -d "$pg_db" \
        | gzip > "$backup_file"
    
    if [ -f "$backup_file" ] && [ -s "$backup_file" ]; then
        local size
        size=$(du -h "$backup_file" | cut -f1)
        log_info "✓ Sauvegarde SQL créée: $backup_file ($size)"
    else
        log_warn "⚠ La sauvegarde SQL peut être vide ou échouée"
    fi
}

backup_config() {
    local timestamp
    timestamp=$(date '+%Y%m%d_%H%M%S')
    local backup_file="${BACKUP_DIR}/config_${timestamp}.tar.gz"
    
    log_info "Sauvegarde de la configuration"
    
    tar czf "$backup_file" \
        -C "$RAG_DIR" \
        infra/.env \
        infra/docker-compose*.yml \
        infra/nginx/*.template \
        infra/prometheus/*.yml \
        2>/dev/null || true
    
    if [ -f "$backup_file" ]; then
        local size
        size=$(du -h "$backup_file" | cut -f1)
        log_info "✓ Sauvegarde config créée: $backup_file ($size)"
    fi
}

backup_full() {
    log_info "=== Démarrage de la sauvegarde COMPLÈTE ==="
    
    # Lister les volumes Docker
    local volumes
    volumes=$(docker volume ls -q | grep "^${COMPOSE_PROJECT}_" || true)
    
    if [ -z "$volumes" ]; then
        log_warn "Aucun volume Docker trouvé pour le projet $COMPOSE_PROJECT"
    else
        for volume in $volumes; do
            backup_volume "$volume" "full"
        done
    fi
    
    # Sauvegarde de la base de données (si pgvector est utilisé)
    if docker ps --format '{{.Names}}' | grep -q "pgvector"; then
        backup_database
    fi
    
    # Sauvegarde de la configuration
    backup_config
    
    log_info "=== Sauvegarde COMPLÈTE terminée ==="
}

backup_incremental() {
    log_info "=== Démarrage de la sauvegarde INCRÉMENTIELLE ==="
    
    # Pour l'instant, on fait une sauvegarde complète
    # Pour une vraie sauvegarde incrémentale, utiliser rsync ou borgbackup
    backup_full
    
    log_info "=== Sauvegarde INCRÉMENTIELLE terminée ==="
}

# ═══════════════════════════════════════════════════════════════════
# Restauration
# ═══════════════════════════════════════════════════════════════════

restore_volume() {
    local volume_name="$1"
    local backup_file="$2"
    
    log_info "Restauration du volume: $volume_name depuis $backup_file"
    
    if [ ! -f "$backup_file" ]; then
        log_error "Fichier de sauvegarde introuvable: $backup_file"
        return 1
    fi
    
    # Arrêter le service qui utilise le volume
    log_warn "Arrêt des services utilisant le volume..."
    docker compose -f "$RAG_DIR/$COMPOSE_FILE" stop || true
    
    # Supprimer l'ancien volume
    docker volume rm "$volume_name" 2>/dev/null || true
    
    # Créer un nouveau volume
    docker volume create "$volume_name"
    
    # Restaurer les données
    docker run --rm \
        -v "$volume_name":/data \
        -v "$(dirname "$backup_file")":/backup:ro \
        busybox tar xzf "/backup/$(basename "$backup_file")" -C /data
    
    log_info "✓ Volume restauré: $volume_name"
    
    # Redémarrer les services
    log_info "Redémarrage des services..."
    docker compose -f "$RAG_DIR/$COMPOSE_FILE" start
}

list_backups() {
    log_info "=== Sauvegardes disponibles ==="
    
    if [ ! -d "$BACKUP_DIR" ]; then
        log_warn "Aucune sauvegarde trouvée"
        return
    fi
    
    echo ""
    echo "Fichiers de sauvegarde dans $BACKUP_DIR :"
    echo "─────────────────────────────────────────"
    ls -lh "$BACKUP_DIR"/*.tar.gz 2>/dev/null || echo "Aucune sauvegarde trouvée"
    echo ""
    ls -lh "$BACKUP_DIR"/*.sql.gz 2>/dev/null || true
    echo "─────────────────────────────────────────"
    
    # Taille totale
    local total_size
    total_size=$(du -sh "$BACKUP_DIR" 2>/dev/null | cut -f1 || echo "N/A")
    echo "Taille totale: $total_size"
}

# ═══════════════════════════════════════════════════════════════════
# Rotation des sauvegardes
# ═══════════════════════════════════════════════════════════════════

rotate_backups() {
    log_info "=== Rotation des sauvegardes ==="
    
    # Supprimer les sauvegardes de plus de RETENTION_DAYS jours
    find "$BACKUP_DIR" -name "*.tar.gz" -type f -mtime +"$RETENTION_DAYS" -delete 2>/dev/null || true
    find "$BACKUP_DIR" -name "*.sql.gz" -type f -mtime +"$RETENTION_DAYS" -delete 2>/dev/null || true
    
    log_info "✓ Sauvegardes de plus de $RETENTION_DAYS jours supprimées"
    
    # Garder une sauvegarde par semaine (les plus anciennes)
    # Garder une sauvegarde par mois (les plus anciennes)
    # (implémentation simplifiée pour l'instant)
    
    log_info "=== Rotation terminée ==="
}

# ═══════════════════════════════════════════════════════════════════
# Installation cron
# ═══════════════════════════════════════════════════════════════════

install_cron() {
    local cron_schedule="${1:-0 2 * * *}"  # Tous les jours à 02:00
    
    log_info "Installation de la tâche cron: $cron_schedule"
    
    local cron_job="SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

# Sauvegarde quotidienne de rag-local
$cron_schedule root $SCRIPT_DIR/backup-rag.sh --incremental >> /var/log/rag-backup.log 2>&1

# Rotation hebdomadaire
0 3 * * 0 root $SCRIPT_DIR/backup-rag.sh --rotate >> /var/log/rag-backup.log 2>&1
"
    
    echo "$cron_job" > /etc/cron.d/rag-local-backup
    chmod 644 /etc/cron.d/rag-local-backup
    
    log_info "✓ Tâche cron installée dans /etc/cron.d/rag-local-backup"
    log_info "  - Sauvegarde incrémentale: $cron_schedule"
    log_info "  - Rotation: Dimanche à 03:00"
}

uninstall_cron() {
    log_info "Désinstallation de la tâche cron"
    rm -f /etc/cron.d/rag-local-backup
    log_info "✓ Tâche cron désinstallée"
}

# ═══════════════════════════════════════════════════════════════════
# Aide
# ═══════════════════════════════════════════════════════════════════

show_help() {
    cat << EOF
Usage: $(basename "$0") [OPTIONS]

Sauvegarde et restauration de rag-local.

OPTIONS:
    --full              Sauvegarde complète (défaut)
    --incremental       Sauvegarde incrémentielle
    --restore=FILE      Restaurer depuis un fichier
    --list              Lister les sauvegardes disponibles
    --rotate            Effectuer la rotation des sauvegardes
    --install-cron      Installer la tâche cron
    --uninstall-cron    Désinstaller la tâche cron
    -h, --help          Afficher cette aide

EXEMPLES:
    $(basename "$0") --full
    $(basename "$0") --incremental
    $(basename "$0") --list
    $(basename "$0") --restore=/var/backups/rag-local/chroma_full_20260301.tar.gz
    $(basename "$0") --install-cron "0 2 * * *"

VARIABLES D'ENVIRONNEMENT:
    RAG_DIR             Répertoire de rag-local (défaut: /srv/rag-local)
    BACKUP_DIR          Répertoire de sauvegarde (défaut: /var/backups/rag-local)
    RETENTION_DAYS      Jours de rétention (défaut: 30)
    COMPOSE_FILE        Fichier Docker Compose (défaut: docker-compose.prod.yml)

EOF
}

# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════

main() {
    check_dependencies
    check_permissions
    
    local action="${1:---full}"
    
    case "$action" in
        --full)
            backup_full
            ;;
        --incremental)
            backup_incremental
            ;;
        --restore=*)
            local file="${action#*=}"
            log_warn "La restauration nécessite de spécifier le volume"
            log_info "Usage manuel: docker run --rm -v volume:/data -v backup:/backup busybox tar xzf /backup/file.tar.gz -C /data"
            ;;
        --list)
            list_backups
            ;;
        --rotate)
            rotate_backups
            ;;
        --install-cron)
            install_cron "${2:-0 2 * * *}"
            ;;
        --uninstall-cron)
            uninstall_cron
            ;;
        -h|--help)
            show_help
            ;;
        *)
            log_error "Option inconnue: $action"
            show_help
            exit 1
            ;;
    esac
}

main "$@"
