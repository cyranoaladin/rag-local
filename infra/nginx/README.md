Ces fichiers sont des **templates** de vhosts Nginx :
- `rag-ui.conf.template` pour l’UI Streamlit (reverse proxy vers 127.0.0.1:__UI_PORT__)
- `rag-n8n.conf.template` pour n8n (reverse proxy vers 127.0.0.1:__N8N_PORT__)

Ils sont pensés pour être rendus avec `envsubst` (pas de syntaxe `${VAR:-def}`), par exemple :

```bash
export RAG_EXTERNAL_DOMAIN="rag.example.com"
export N8N_EXTERNAL_DOMAIN="automations.example.com"
export NGINX_UI_PORT="18501"
export NGINX_N8N_PORT="15678"
export NGINX_CLIENT_MAX_BODY_SIZE="${NGINX_CLIENT_MAX_BODY_SIZE:-16m}"

envsubst < infra/nginx/rag-ui.conf.template  | sudo tee /etc/nginx/sites-available/rag-ui.conf  >/dev/null
envsubst < infra/nginx/rag-n8n.conf.template | sudo tee /etc/nginx/sites-available/rag-n8n.conf >/dev/null
sudo ln -sf /etc/nginx/sites-available/rag-ui.conf  /etc/nginx/sites-enabled/rag-ui.conf
sudo ln -sf /etc/nginx/sites-available/rag-n8n.conf /etc/nginx/sites-enabled/rag-n8n.conf
sudo nginx -t && sudo systemctl reload nginx
```

Ensuite, **Certbot** peut gérer la terminaison TLS :

```bash
sudo certbot --nginx -d <domaine> -m <email> --agree-tos --no-eff-email
```

Certbot ajoutera automatiquement les blocs HTTPS.
