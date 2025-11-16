# Guide d’upgrade vers v1.1.0

Ce guide décrit les changements à appliquer pour passer de v1.0.0 à v1.1.0 en production.

## TL;DR
- Nouvelle Admin API (CRUD + upload + listings): `/admin/*` ajoutée à l’ingestor.
- Persistance du catalog Admin (SQLite): `ADMIN_DB_PATH=/data/catalog.sqlite` + volume `rag_admin_data:/data`.
- Uploads en écriture: `/srv/rag-data` → `/data/uploads:rw` dans le conteneur ingestor.
- UI: section d’upload intégrée.

## Étapes

1) Mettre à jour l’arborescence et les templates
- Récupérer la nouvelle version (git pull + checkout du tag `v1.1.0`).
- Vérifier que `infra/docker-compose.prod.yml` contient:
  - `ADMIN_DB_PATH=/data/catalog.sqlite`
  - Volume `rag_admin_data:/data`
  - Montages: `/srv/rag-data:/data/uploads:rw`

2) Préparer les répertoires sur le VPS
```bash
sudo mkdir -p /srv/rag-data
sudo chown -R $USER:$USER /srv/rag-data
```

3) Variables d’environnement (`infra/.env`)
- Conserver `INGESTOR_API_TOKEN`.
- Ajouter/valider si besoin:
  - `NGINX_CLIENT_MAX_BODY_SIZE=64m` (si vous uploadez de gros PDF)
  - `ADMIN_DB_PATH=/data/catalog.sqlite`
  - `ADMIN_UPLOAD_DIR=/data/uploads`

4) Redéployer l’ingestor et l’UI
```bash
cd /srv/rag-local
# si vous utilisez systemd, redémarrez le service; sinon compose:
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env up -d --build ingestor ui
```

5) Valider en prod
```bash
# API Ingestor
echo $INGESTOR_API_TOKEN | wc -c  # ne pas afficher le token en clair
curl -sS https://<RAG_API_DOMAIN>/health | jq .
# Admin API (endpoints publics de santé/reindex)
curl -sS https://<RAG_API_DOMAIN>/admin/health | jq .
curl -sS -X POST https://<RAG_API_DOMAIN>/admin/reindex | jq .  # 503 attendu (non configuré)
# Upload avec ingestion
curl -sS -H "Authorization: Bearer $INGESTOR_API_TOKEN" \
  -F "file=@./README.md" \
  "https://<RAG_API_DOMAIN>/admin/upload?ingest=true&domain=lycee&title=README" | jq .
```

6) Google Drive (inchangé)
- Voir `infra/scripts/enable-gdrive-prod.sh` et `README-PROD.md`.

## Notes de compatibilité
- Python 3.9 est supporté (polyfills appliqués) mais la stack conseille ≥3.10.
- `/admin/health` et `/admin/reindex` sont publics pour compat automatisations/tests; restreignez via Nginx si nécessaire.

## Rollback
- Revenir au tag v1.0.0 et reconstruire:
```bash
git checkout v1.0.0
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env up -d --build ingestor ui
```
