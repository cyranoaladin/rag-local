Ces fichiers sont des **templates** de vhosts Nginx :
- `rag-ui.conf.template` pour l’UI Streamlit (reverse proxy vers 127.0.0.1:__UI_PORT__)
- `rag-n8n.conf.template` pour n8n (reverse proxy vers 127.0.0.1:__N8N_PORT__)

## Rendu des vhosts via `envsubst`

```bash
# Variables explicitement définies (pas de ${VAR:-def})
export RAG_EXTERNAL_DOMAIN="dummy.local"
export N8N_EXTERNAL_DOMAIN="dummy-n8n.local"
export NGINX_UI_PORT="18501"
export NGINX_N8N_PORT="15678"
export NGINX_CLIENT_MAX_BODY_SIZE="16m"

# Rendu + activation
sudo -E bash -c 'envsubst < infra/nginx/rag-ui.conf.template  > /etc/nginx/sites-available/rag-ui.conf'
sudo -E bash -c 'envsubst < infra/nginx/rag-n8n.conf.template > /etc/nginx/sites-available/rag-n8n.conf'
sudo ln -sf /etc/nginx/sites-available/rag-ui.conf  /etc/nginx/sites-enabled/rag-ui.conf
sudo ln -sf /etc/nginx/sites-available/rag-n8n.conf /etc/nginx/sites-enabled/rag-n8n.conf
sudo nginx -t && sudo systemctl reload nginx
```

Ensuite, **Certbot** peut gérer la terminaison TLS :

```bash
sudo certbot --nginx -d <domaine> -m <email> --agree-tos --no-eff-email
```

Certbot ajoutera automatiquement les blocs HTTPS.
Ajoutez `add_header Strict-Transport-Security "max-age=63072000" always;` dans les blocs HTTPS de production.
