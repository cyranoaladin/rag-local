# PR checks for Nginx web service

```bash
# Compose validates
docker compose -f infra/docker-compose.yml --env-file infra/.env config >/dev/null && echo "compose: OK"

docker compose -f infra/docker-compose.yml --env-file infra/.env config | awk '/services:/{f=1} f && /ui:|n8n:|web:|profiles:|ports:/{print}'

grep -R '\${[^}]*:-' infra/nginx -n || echo "OK: no shell-defaults in templates"

make nginx-render && grep -E 'proxy_pass' -n infra/nginx/rendered/*.conf

# Optional: bring up only Nginx with dev override and verify health
docker compose -f infra/docker-compose.yml -f infra/docker-compose.dev.yml --env-file infra/.env up -d web

docker compose -f infra/docker-compose.yml --env-file infra/.env ps web

docker compose -f infra/docker-compose.yml --env-file infra/.env exec -T web nginx -t
```
