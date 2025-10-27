# EPIC Infra (prod)
Objectif: Infra prête pour VPS (CPU-only), TLS via Nginx, backups des volumes.
## Tâches
- [ ] Compose sans `version:`, profils (`db`,`llm`,`api`,`ui`,`web`)
- [ ] Healthchecks: Chroma /v2/heartbeat, Ingestor /health (grace), UI /
- [ ] depends_on: ingestor→(Chroma,Ollama), UI→(Chroma,Ingestor)
- [ ] Sécurité conteneurs: user non-root, read_only, tmpfs, no-new-privileges
- [ ] Ressources: limites CPU/RAM via `.env`
- [ ] Nginx + TLS (vhosts + certbot)
- [ ] Backups: scripts volumes (chroma, n8n) + restauration
- [ ] Tests d’acceptation (README-PROD)
