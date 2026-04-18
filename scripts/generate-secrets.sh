#!/usr/bin/env bash
#
# generate-secrets.sh — Génère les secrets de production pour rag-local
# Usage: ./scripts/generate-secrets.sh [--output=infra/.env]
#
# Auteur : Alaeddine BEN RHOUMA
# Date : Mars 2026
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
OUTPUT_FILE="${OUTPUT_FILE:-${PROJECT_ROOT}/infra/.env}"

# Couleurs pour les messages
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Génère un token hex aléatoire de la longueur spécifiée
generate_hex_token() {
    local length="${1:-32}"
    openssl rand -hex "$length"
}

# Génère un mot de passe aléatoire
generate_password() {
    local length="${1:-32}"
    openssl rand -base64 "$length" | tr -dc 'a-zA-Z0-9' | head -c "$length"
}

# Vérifie si openssl est disponible
check_dependencies() {
    if ! command -v openssl &> /dev/null; then
        log_error "openssl n'est pas installé. Veuillez l'installer."
        exit 1
    fi
}

# Lit la valeur actuelle d'une variable depuis le fichier .env
get_env_value() {
    local key="$1"
    local file="$2"
    if [ -f "$file" ]; then
        grep -E "^${key}=" "$file" 2>/dev/null | tail -n 1 | cut -d'=' -f2- || echo ""
    else
        echo ""
    fi
}

# Met à jour ou ajoute une variable dans le fichier .env
set_env_value() {
    local key="$1"
    local value="$2"
    local file="$3"
    
    if grep -qE "^${key}=" "$file" 2>/dev/null; then
        # La variable existe, la mettre à jour
        local temp_file
        temp_file=$(mktemp)
        sed "s|^${key}=.*|${key}=${value}|" "$file" > "$temp_file"
        mv "$temp_file" "$file"
    else
        # La variable n'existe pas, l'ajouter
        echo "${key}=${value}" >> "$file"
    fi
}

# Affiche l'aide
show_help() {
    cat << EOF
Usage: $(basename "$0") [OPTIONS]

Génère les secrets de production pour rag-local.

OPTIONS:
    -o, --output=FILE    Fichier de sortie (défaut: infra/.env)
    -u, --update         Mettre à jour uniquement les secrets manquants
    -f, --force          Écraser les secrets existants
    -h, --help           Affiche cette aide

EXEMPLES:
    $(basename "$0")                      # Génère tous les secrets
    $(basename "$0") --update             # Génère uniquement les secrets manquants
    $(basename "$0") --output=/srv/rag/.env

SECRETS GÉNÉRÉS:
    - INGESTOR_API_TOKEN (64 hex)     Authentification API ingestion
    - INGEST_AUTH_TOKEN (64 hex)      Authentification webhook (compatibilité)
    - N8N_ENCRYPTION_KEY (64 hex)     Chiffrement n8n
    - N8N_BASIC_AUTH_PASSWORD (32)    Mot de passe BasicAuth n8n
    - PROMETHEUS_SCRAPE_PASSWORD (32) Authentification Prometheus
    - API_SECRET_KEY (64 hex)         Clé secrète API v2
    - REDIS_PASSWORD (32)             Mot de passe Redis
    - PGVECTOR_PASSWORD (32)          Mot de passe PostgreSQL
    - UI_SECRET_KEY (64 hex)          Clé secrète Streamlit

EOF
}

# Fonction principale
main() {
    local update_only=false
    local force=false
    
    # Parse les arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            -o|--output)
                OUTPUT_FILE="$2"
                shift 2
                ;;
            -o=*|--output=*)
                OUTPUT_FILE="${1#*=}"
                shift
                ;;
            -u|--update)
                update_only=true
                shift
                ;;
            -f|--force)
                force=true
                shift
                ;;
            -h|--help)
                show_help
                exit 0
                ;;
            *)
                log_error "Option inconnue: $1"
                show_help
                exit 1
                ;;
        esac
    done
    
    # Vérifie les dépendances
    check_dependencies
    
    # Crée le répertoire de sortie s'il n'existe pas
    local output_dir
    output_dir="$(dirname "$OUTPUT_FILE")"
    if [ ! -d "$output_dir" ]; then
        log_info "Création du répertoire: $output_dir"
        mkdir -p "$output_dir"
    fi
    
    # Crée le fichier .env s'il n'existe pas
    if [ ! -f "$OUTPUT_FILE" ]; then
        log_info "Création du fichier: $OUTPUT_FILE"
        touch "$OUTPUT_FILE"
    fi
    
    log_info "Génération des secrets de production..."
    log_warn "⚠️  IMPORTANT : Conservez ces secrets en sécurité !"
    log_warn "⚠️  Ne commitez JAMAIS ce fichier dans Git."
    echo ""
    
    # Génère chaque secret
    local secrets_generated=0
    local secrets_skipped=0
    
    # INGESTOR_API_TOKEN
    current_value=$(get_env_value "INGESTOR_API_TOKEN" "$OUTPUT_FILE")
    if [ -n "$current_value" ] && [ "$update_only" = true ] && [ "$force" = false ]; then
        log_info "INGESTOR_API_TOKEN: conservé (déjà défini)"
        ((secrets_skipped++))
    else
        new_value=$(generate_hex_token 32)
        set_env_value "INGESTOR_API_TOKEN" "$new_value" "$OUTPUT_FILE"
        log_info "INGESTOR_API_TOKEN: généré"
        ((secrets_generated++))
    fi
    
    # INGEST_AUTH_TOKEN (pour compatibilité)
    current_value=$(get_env_value "INGEST_AUTH_TOKEN" "$OUTPUT_FILE")
    if [ -n "$current_value" ] && [ "$update_only" = true ] && [ "$force" = false ]; then
        log_info "INGEST_AUTH_TOKEN: conservé (déjà défini)"
        ((secrets_skipped++))
    else
        # Utilise la même valeur que INGESTOR_API_TOKEN pour la compatibilité
        ingestor_token=$(get_env_value "INGESTOR_API_TOKEN" "$OUTPUT_FILE")
        set_env_value "INGEST_AUTH_TOKEN" "$ingestor_token" "$OUTPUT_FILE"
        log_info "INGEST_AUTH_TOKEN: synchronisé avec INGESTOR_API_TOKEN"
        ((secrets_generated++))
    fi
    
    # N8N_ENCRYPTION_KEY
    current_value=$(get_env_value "N8N_ENCRYPTION_KEY" "$OUTPUT_FILE")
    if [ -n "$current_value" ] && [ "$update_only" = true ] && [ "$force" = false ]; then
        log_info "N8N_ENCRYPTION_KEY: conservé (déjà défini)"
        ((secrets_skipped++))
    else
        new_value=$(generate_hex_token 32)
        set_env_value "N8N_ENCRYPTION_KEY" "$new_value" "$OUTPUT_FILE"
        log_info "N8N_ENCRYPTION_KEY: généré"
        ((secrets_generated++))
    fi
    
    # N8N_BASIC_AUTH_PASSWORD
    current_value=$(get_env_value "N8N_BASIC_AUTH_PASSWORD" "$OUTPUT_FILE")
    if [ -n "$current_value" ] && [ "$update_only" = true ] && [ "$force" = false ]; then
        log_info "N8N_BASIC_AUTH_PASSWORD: conservé (déjà défini)"
        ((secrets_skipped++))
    else
        new_value=$(generate_password 32)
        set_env_value "N8N_BASIC_AUTH_PASSWORD" "$new_value" "$OUTPUT_FILE"
        log_info "N8N_BASIC_AUTH_PASSWORD: généré"
        ((secrets_generated++))
    fi
    
    # PROMETHEUS_SCRAPE_PASSWORD
    current_value=$(get_env_value "PROMETHEUS_SCRAPE_PASSWORD" "$OUTPUT_FILE")
    if [ -n "$current_value" ] && [ "$update_only" = true ] && [ "$force" = false ]; then
        log_info "PROMETHEUS_SCRAPE_PASSWORD: conservé (déjà défini)"
        ((secrets_skipped++))
    else
        new_value=$(generate_password 32)
        set_env_value "PROMETHEUS_SCRAPE_PASSWORD" "$new_value" "$OUTPUT_FILE"
        log_info "PROMETHEUS_SCRAPE_PASSWORD: généré"
        ((secrets_generated++))
    fi
    
    # API_SECRET_KEY (v2)
    current_value=$(get_env_value "API_SECRET_KEY" "$OUTPUT_FILE")
    if [ -n "$current_value" ] && [ "$update_only" = true ] && [ "$force" = false ]; then
        log_info "API_SECRET_KEY: conservé (déjà défini)"
        ((secrets_skipped++))
    else
        new_value=$(generate_hex_token 32)
        set_env_value "API_SECRET_KEY" "$new_value" "$OUTPUT_FILE"
        log_info "API_SECRET_KEY: généré"
        ((secrets_generated++))
    fi
    
    # REDIS_PASSWORD
    current_value=$(get_env_value "REDIS_PASSWORD" "$OUTPUT_FILE")
    if [ -n "$current_value" ] && [ "$update_only" = true ] && [ "$force" = false ]; then
        log_info "REDIS_PASSWORD: conservé (déjà défini)"
        ((secrets_skipped++))
    else
        new_value=$(generate_password 32)
        set_env_value "REDIS_PASSWORD" "$new_value" "$OUTPUT_FILE"
        log_info "REDIS_PASSWORD: généré"
        ((secrets_generated++))
    fi
    
    # PGVECTOR_PASSWORD
    current_value=$(get_env_value "PGVECTOR_PASSWORD" "$OUTPUT_FILE")
    if [ -n "$current_value" ] && [ "$update_only" = true ] && [ "$force" = false ]; then
        log_info "PGVECTOR_PASSWORD: conservé (déjà défini)"
        ((secrets_skipped++))
    else
        new_value=$(generate_password 32)
        set_env_value "PGVECTOR_PASSWORD" "$new_value" "$OUTPUT_FILE"
        log_info "PGVECTOR_PASSWORD: généré"
        ((secrets_generated++))
    fi
    
    # UI_SECRET_KEY
    current_value=$(get_env_value "UI_SECRET_KEY" "$OUTPUT_FILE")
    if [ -n "$current_value" ] && [ "$update_only" = true ] && [ "$force" = false ]; then
        log_info "UI_SECRET_KEY: conservé (déjà défini)"
        ((secrets_skipped++))
    else
        new_value=$(generate_hex_token 32)
        set_env_value "UI_SECRET_KEY" "$new_value" "$OUTPUT_FILE"
        log_info "UI_SECRET_KEY: généré"
        ((secrets_generated++))
    fi
    
    echo ""
    log_info "✅ Secrets générés : $secrets_generated"
    if [ "$secrets_skipped" -gt 0 ]; then
        log_info "ℹ️  Secrets conservés : $secrets_skipped"
    fi
    
    # Définit les permissions sécurisées sur le fichier
    chmod 600 "$OUTPUT_FILE"
    log_info "🔒 Permissions définies : 600 (lecture/écriture propriétaire uniquement)"
    
    echo ""
    log_warn "⚠️  Prochaines étapes :"
    echo "    1. Vérifiez le fichier : cat $OUTPUT_FILE"
    echo "    2. Personnalisez les autres variables d'environnement"
    echo "    3. Ne commitez JAMAIS ce fichier dans Git"
    echo ""
}

# Exécute la fonction principale
main "$@"
