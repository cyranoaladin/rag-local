#!/bin/bash
# rag_diag_vps.sh — Diagnostic complet RAG pour VPS

set -e

BASE="/srv/rag-local"
INFRA="$BASE/infra"
NGINX_TPL="$INFRA/nginx"
NGINX_RENDERED="$NGINX_TPL/rendered"
ENV="$INFRA/.env"
ENV_EX="$INFRA/.env.example"
UI_ENV="$BASE/src/ui/.env"
DC="$INFRA/docker-compose.yml"
DC_DEV="$INFRA/docker-compose.dev.yml"
DC_OBS="$INFRA/docker-compose.obs.yml"
DC_TEST="$INFRA/docker-compose.test.yml"
MAKEFILE="$BASE/Makefile"
SMOKE="$INFRA/scripts/smoke.sh"
API="$BASE/src/ingestor/api.py"
UI="$BASE/src/ui"
NGINX_CONF="/etc/nginx/nginx.conf"
NGINX_SITES="/etc/nginx/sites-enabled"
NGINX_ERROR_LOG="/var/log/nginx/error.log"

echo "=== [1] Nginx — Templates vhost ==="
for f in "$NGINX_TPL"/rag-ui.conf.template "$NGINX_TPL"/rag-n8n.conf.template; do
    if [ -f "$f" ]; then
        echo "Présent : $f"
        head -n 5 "$f"
    else
        echo "Absent : $f"
    fi
done

echo -e "\n=== [2] Nginx — Vhosts rendus ==="
for f in "$NGINX_RENDERED"/rag-ui.conf "$NGINX_RENDERED"/rag-n8n.conf; do
    if [ -f "$f" ]; then
        echo "Présent : $f"
        head -n 5 "$f"
    else
        echo "Absent : $f"
    fi
done

echo -e "\n=== [3] Nginx — Config système ==="
if [ -f "$NGINX_CONF" ]; then
    echo "nginx.conf présent"
    grep -E 'server_name|include' "$NGINX_CONF" || echo "Aucun server_name/include dans nginx.conf"
else
    echo "nginx.conf absent"
fi
if [ -d "$NGINX_SITES" ]; then
    echo "sites-enabled :"
    ls -l "$NGINX_SITES"
    grep -E 'server_name' "$NGINX_SITES"/* 2>/dev/null || echo "Aucun server_name dans les vhosts activés"
else
    echo "Dossier sites-enabled absent"
fi

echo -e "\n=== [4] Nginx — Logs erreurs (20 dernières lignes) ==="
if [ -f "$NGINX_ERROR_LOG" ]; then
    tail -n 20 "$NGINX_ERROR_LOG"
else
    echo "Log d'erreur Nginx absent"
fi

echo -e "\n=== [5] Clés API (.env) ==="
if [ -f "$ENV" ]; then
    echo ".env présent"
    grep -E 'INGESTOR_API_TOKEN|INGEST_API_TOKEN' "$ENV" || echo "Clé API absente du .env"
else
    echo ".env absent"
fi
if [ -f "$ENV_EX" ]; then
    echo ".env.example présent"
    head -n 5 "$ENV_EX"
else
    echo ".env.example absent"
fi
if [ -f "$UI_ENV" ]; then
    echo "src/ui/.env présent"
    grep -E 'INGESTOR_API_TOKEN|INGEST_API_TOKEN' "$UI_ENV" || echo "Clé API absente dans src/ui/.env"
else
    echo "src/ui/.env absent"
fi

echo -e "\n=== [6] Docker Compose — Services et overrides ==="
for f in "$DC" "$DC_DEV" "$DC_OBS" "$DC_TEST"; do
    if [ -f "$f" ]; then
        echo "Présent : $f"
        grep -E 'ingestor|ui|n8n|chroma|ollama|web' "$f" | grep 'image\|ports\|environment' || echo "Services non trouvés dans $f"
    else
        echo "Absent : $f"
    fi
done

echo -e "\n=== [7] Makefile & scripts ==="
if [ -f "$MAKEFILE" ]; then
    echo "Makefile présent"
    grep -E 'compose-up|compose-down|logs' "$MAKEFILE" || echo "Cibles compose-up/down/logs absentes"
else
    echo "Makefile absent"
fi
if [ -f "$SMOKE" ]; then
    echo "smoke.sh présent"
    head -n 5 "$SMOKE"
else
    echo "smoke.sh absent"
fi

echo -e "\n=== [8] Endpoints — API & UI ==="
if [ -f "$API" ]; then
    echo "api.py présent"
    head -n 5 "$API"
else
    echo "api.py absent"
fi
if [ -d "$UI" ]; then
    echo "ui (Streamlit) présent"
    ls -l "$UI"
else
    echo "ui absent"
fi
echo "Test endpoints locaux (dev):"
curl -s -o /dev/null -w "API /health: %{http_code}\n" http://127.0.0.1:18001/health || echo "API /health inaccessible"
curl -s -o /dev/null -w "API /metrics: %{http_code}\n" http://127.0.0.1:18001/metrics || echo "API /metrics inaccessible"
curl -s -o /dev/null -w "UI (Streamlit): %{http_code}\n" http://127.0.0.1:18080 || echo "UI (Streamlit) inaccessible"

echo -e "\n=== [9] Fichiers critiques — Résumé ==="
for f in "$ENV" "$DC" "$NGINX_TPL"/rag-ui.conf.template "$NGINX_TPL"/rag-n8n.conf.template "$NGINX_RENDERED"/rag-ui.conf "$NGINX_RENDERED"/rag-n8n.conf "$API"; do
    if [ -e "$f" ]; then
        echo "Présent : $f"
    else
        echo "Absent : $f"
    fi
done

echo -e "\n=== [10] Résumé rapide ==="
echo "Vérifie les points signalés ci-dessus. Corrige toute absence ou incohérence selon la documentation du projet."
