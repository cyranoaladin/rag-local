# Checklist d'exploitation VPS

## Prérequis infra
- VPS Linux 64 bits (Ubuntu 22.04/24.04 recommandé) avec accès `sudo` et ports 80/443 ouverts.
- Docker Engine ≥ 24.0 et plugin Docker Compose ≥ 2.24 (`docker compose version`).
- Espace disque libre :
  - 5 Go pour `rag_ollama_data` (modèles `nomic-embed-text`, `llama3.2:latest`).
  - 2 Go pour `rag_chroma_data` (index vectoriel initial).
  - 1 Go pour `rag_n8n_data` + marge pour journaux.
  - 2 Go supplémentaires pour sauvegardes (`infra/backups`).
- DNS pointant `RAG_EXTERNAL_DOMAIN` et `N8N_EXTERNAL_DOMAIN` vers le VPS.

## Pré-déploiement
- Copier `infra/.env.production.sample` vers `infra/.env` et ajuster domaines, secrets et allowlists.
- Lancer `infra/scripts/ollama-preload.sh` pour télécharger les modèles nécessaires avant la mise en service.
- Vérifier l'espace disque pour les volumes `rag_chroma_data`, `rag_ollama_data`, `rag_n8n_data`.

## Déploiement
- Démarrer la stack :
  - `docker compose -f infra/docker-compose.yml --env-file infra/.env up -d`
  - Ou `COMPOSE_PROFILES=db,llm,api,ui,automations,web docker compose ... up -d`
- Exécuter `infra/scripts/smoke.sh` pour valider la santé du cluster.
- Inspecter les journaux : `make logs` ou `docker compose logs --tail 200`.

## Frontend HTTPS
- Rendre les fichiers `infra/nginx/rag-ui.conf.template` et `infra/nginx/rag-n8n.conf.template` avec `envsubst`.
- Déployer les vhosts dans `/etc/nginx/sites-available`, activer les liens symboliques et recharger Nginx.
- Obtenir les certificats Let's Encrypt via `certbot --nginx ...` puis ajouter la directive HSTS.
- Restreindre `/metrics` aux IP internes dans la configuration Nginx si Prometheus est exposé.

## Sécurité
- Activer `INGESTOR_IP_ALLOWLIST` si l'API doit être limitée.
- Définir (ou renforcer) l'entête `INGEST_AUTH_HEADER`; vérifier que l'UI fournit le même jeton.
- Remplir les directives Basic Auth (`UI_BASIC_AUTH_*`) si l'interface Streamlit n'est pas publique.
- Confirmer les variables n8n (`N8N_BASIC_AUTH_*`, `N8N_ENCRYPTION_KEY`).

## Supervision
- Activer `METRICS_ENABLED=true` pour l'ingestor.
- Démarrer le profil observabilité : `COMPOSE_PROFILES=db,llm,api,obs docker compose ... up -d`.
- Configurer Prometheus/Grafana selon `docs/observability.md` et créer les alertes :
- Configurer Prometheus/Grafana selon `docs/observability.md` (section « Déploiement rapide ») et créer les alertes :
  - `ingestor_ingests_total` (statuts ≠ success)
  - `histogram_quantile(0.99, rate(ingestor_ingest_duration_seconds_bucket[5m]))`
- Mettre en place la rotation des logs Docker (`max-size`, `max-file` déjà configurés) et du reverse proxy.

## Sauvegarde & restauration
- Lancer périodiquement `infra/scripts/backup-volumes.sh` (via cron ou systemd timer).
- Utiliser `infra/scripts/restore-volumes.sh <archive> <volume>` pour restaurer un volume.
- Sauvegarder également `infra/creds/` et `infra/data/uploads/` via rsync/restic.

## Post-déploiement
- Tester l'ingestion via l'UI Streamlit (formulaire API et webhook n8n).
- Tester la recherche (top-k) et valider les métadonnées retournées.
- Vérifier que les modèles Ollama restent chargés (`docker compose exec ollama ollama ps`).

## Surveillance continue
- Suivre les jobs GitHub Actions `CI Smoke (Compose)` après chaque mise à jour.
- Monitorer l'espace disque (`df -h`, `docker system df`) et la charge CPU/mémoire.
- Consulter régulièrement les journaux d'ingestion pour détecter les HTTP 4xx/5xx.
