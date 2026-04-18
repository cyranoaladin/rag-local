Ces fichiers sont des **templates** de vhosts Nginx (hôte) :
- `rag-ui.conf.template` pour l’UI Streamlit (reverse proxy vers 127.0.0.1:8501, Basic Auth requise)
- `rag-api.conf.template` pour l’API Ingestor (reverse proxy vers 127.0.0.1:${NGINX_API_PORT}, `/metrics` restreint à 127.0.0.1)

## Rendu des vhosts via `envsubst`

```bash
# Variables explicitement définies (pas de ${VAR:-def})
export RAG_UI_EXTERNAL_DOMAIN="rag-ui.example.com"
export RAG_API_EXTERNAL_DOMAIN="rag-api.example.com"
export NGINX_API_PORT="8001"
export NGINX_CLIENT_MAX_BODY_SIZE="16m"

# Rendu + activation
sudo -E bash -c 'envsubst < infra/nginx/rag-ui.conf.template  > /etc/nginx/sites-available/rag-ui.conf'
sudo -E bash -c 'envsubst < infra/nginx/rag-api.conf.template > /etc/nginx/sites-available/rag-api.conf'
sudo ln -sf /etc/nginx/sites-available/rag-ui.conf  /etc/nginx/sites-enabled/rag-ui.conf
sudo ln -sf /etc/nginx/sites-available/rag-api.conf /etc/nginx/sites-enabled/rag-api.conf
sudo nginx -t && sudo systemctl reload nginx
```

Ensuite, **Certbot** peut gérer la terminaison TLS :

```bash
sudo certbot --nginx -d "$RAG_UI_EXTERNAL_DOMAIN" --redirect
sudo certbot --nginx -d "$RAG_API_EXTERNAL_DOMAIN" --redirect
```

Certbot ajoutera automatiquement les blocs HTTPS.
Ajoutez `add_header Strict-Transport-Security "max-age=63072000" always;` dans les blocs HTTPS de production.

## Rate limiting
- Le vhost API inclut une zone `limit_req_zone` (20 r/s, burst 40) appliquée à `/ingest` et `/search`.
- Ajustez ces valeurs si nécessaire en éditant `infra/nginx/rag-api.conf.template` avant rendu.
