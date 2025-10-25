Ces fichiers sont des **templates** de vhosts Nginx :
- `rag-ui.conf.template` pour l’UI Streamlit (reverse proxy vers 127.0.0.1:__UI_PORT__)
- `rag-n8n.conf.template` pour n8n (reverse proxy vers 127.0.0.1:__N8N_PORT__)

Étapes (sur le VPS, root/sudo) :
1) Copier le template dans `/etc/nginx/sites-available/` en remplaçant `__UI_DOMAIN__` / `__N8N_DOMAIN__` et `__UI_PORT__` / `__N8N_PORT__`.
2) `ln -s` dans `/etc/nginx/sites-enabled/`.
3) `nginx -t && systemctl reload nginx`
4) **Certbot** : `sudo certbot --nginx -d <domaine> -m <email> --agree-tos --no-eff-email`
   - Certbot ajoutera automatiquement les blocs HTTPS.
