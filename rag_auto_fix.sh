#!/bin/bash
# rag_auto_fix.sh — Correction automatique RAG

set -euo pipefail

BASE="/srv/rag-local"
INFRA="$BASE/infra"
NGINX_TPL="$INFRA/nginx"
NGINX_RENDERED="$NGINX_TPL/rendered"
ENV="$INFRA/.env"
UI_ENV="$BASE/src/ui/.env"
DC="$INFRA/docker-compose.yml"

echo "=== [1] Génération des vhosts Nginx rendus ==="
mkdir -p "$NGINX_RENDERED"

if [ -f "$ENV" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV"
    set +a
else
    echo "Fichier d'environnement manquant: $ENV" >&2
    exit 1
fi

render_template() {
    local tpl_name="$1" src="$2" dest="$3" vars
    case "$tpl_name" in
        rag-ui.conf.template)
            vars='${RAG_EXTERNAL_DOMAIN} ${NGINX_CLIENT_MAX_BODY_SIZE} ${UI_BASIC_AUTH_DIRECTIVE} ${UI_BASIC_AUTH_USER_FILE_DIRECTIVE} ${NGINX_UI_UPSTREAM}'
            ;;
        rag-n8n.conf.template)
            vars='${N8N_EXTERNAL_DOMAIN} ${NGINX_CLIENT_MAX_BODY_SIZE} ${N8N_BASIC_AUTH_DIRECTIVE} ${N8N_BASIC_AUTH_USER_FILE_DIRECTIVE} ${NGINX_N8N_UPSTREAM}'
            ;;
        rag-api.conf.template)
            vars='${API_EXTERNAL_DOMAIN} ${NGINX_CLIENT_MAX_BODY_SIZE} ${API_BASIC_AUTH_DIRECTIVE} ${API_BASIC_AUTH_USER_FILE_DIRECTIVE} ${NGINX_API_UPSTREAM}'
            ;;
        *)
            vars=''
            ;;
    esac
    if [ -n "$vars" ]; then
        envsubst "$vars" < "$src" > "$dest"
    else
        envsubst < "$src" > "$dest"
    fi
    echo "Généré : $dest"
}

for tpl in rag-ui.conf.template rag-api.conf.template rag-n8n.conf.template; do
    src="$NGINX_TPL/$tpl"
    dest="$NGINX_RENDERED/${tpl/.template/}"
    if [ -f "$src" ]; then
        render_template "$tpl" "$src" "$dest"
    else
        echo "Template manquant : $src"
    fi
done

echo "=== [2] Rechargement de Nginx ==="
nginx -t && systemctl reload nginx && echo "Nginx rechargé" || echo "Erreur Nginx, vérifiez la config"

echo "=== [3] Vérification et démarrage des services Docker Compose ==="
docker compose -f "$DC" --env-file "$ENV" up -d web ui ingestor n8n && echo "Services ingestor/ui/web/n8n démarrés"

echo "=== [4] Propagation de la clé API dans src/ui/.env ==="
if [ ! -f "$UI_ENV" ]; then
    grep -E 'INGESTOR_API_TOKEN|INGEST_API_TOKEN' "$ENV" > "$UI_ENV" && echo "Clé API propagée dans src/ui/.env"
else
    echo "src/ui/.env déjà présent"
fi

echo "=== [5] Vérification finale ==="
for rendered in "$NGINX_RENDERED"/rag-ui.conf "$NGINX_RENDERED"/rag-api.conf "$NGINX_RENDERED"/rag-n8n.conf; do
    if [ -f "$rendered" ]; then
        ls -l "$rendered"
    else
        echo "Manquant : $rendered"
    fi
done
docker compose -f "$DC" ps
curl -s -o /dev/null -w "API /health: %{http_code}\n" http://127.0.0.1:18001/health
if [ -n "${RAG_EXTERNAL_DOMAIN:-}" ]; then
    curl -s -o /dev/null -H "Host: ${RAG_EXTERNAL_DOMAIN}" -w "UI (Streamlit via Nginx): %{http_code}\n" http://127.0.0.1:18080/
fi
if [ -n "${API_EXTERNAL_DOMAIN:-}" ]; then
    curl -s -o /dev/null -H "Host: ${API_EXTERNAL_DOMAIN}" -w "API via Nginx /health: %{http_code}\n" http://127.0.0.1:18080/health
fi
