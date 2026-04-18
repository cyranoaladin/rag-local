# rag-local — Troubleshooting Guide

**Author: Alaeddine BEN RHOUMA**

---

## 1. Stack does not start / containers unhealthy
- Run: `bash infra/scripts/smoke.sh` and check output.
- Check `docker compose ps -a` for container status.
- Inspect logs: `docker compose logs --tail 200` or `docker logs <container>`.
- If `ingestor` is unhealthy:
  - Check `/health` endpoint: `curl http://127.0.0.1:18001/health`
  - Ensure all required env vars are set (`infra/.env`).
  - Check for missing Ollama models (see logs for 404/model errors).
- If `chroma` or `ollama` is unhealthy:
  - Check disk space and permissions on volumes.
  - Restart stack: `docker compose down -v && docker compose up -d`

## 2. Ingestion fails (POST /ingest)
- Check API token: header `X-API-Token` must match `INGESTOR_API_TOKEN`.
- Check allowlist: your IP must be in `INGESTOR_IP_ALLOWLIST` (prod).
- For remote URLs: ensure they are reachable from the VPS, not private IPs.
- For file uploads: file must be in allowed directory (`/data/uploads`).
- For GDrive: check service account JSON and permissions.
- For multimodal: check `MULTIMODAL_ENABLED` and model availability.

## 3. UI not accessible / Nginx issues
- Check Nginx config: `nginx -t` and `systemctl status nginx`.
- Ensure vhosts are rendered with `envsubst` and enabled.
- Check firewall: ports 80/443 open, no UFW/iptables block.
- For BasicAuth: check `.htpasswd` files and env vars.
- For HTTPS: check certbot logs and certificate validity.

## 4. Metrics endpoint not working
- Ensure `METRICS_ENABLED=true` in `.env`.
- Check `/metrics` endpoint: `curl http://127.0.0.1:18001/metrics` (should return Prometheus format).
- If 404: metrics are disabled or env var not set.
- For Prometheus: check scrape config and network access to ingestor.

## 5. CI/CD pipeline fails
- Check full logs in GitHub Actions (all logs and diagnostics are dumped on failure).
- Run locally: `make lint && make typecheck && make test && bash infra/scripts/smoke.sh`
- Common causes:
  - Missing or misconfigured `.env`
  - Port conflicts or firewall rules
  - Outdated dependencies (`pip install -r requirements-dev.txt`)
  - Docker Compose version mismatch

## 6. Ollama model errors
- Check model list: `docker exec <ollama-container> ollama list`
- Preload models: `infra/scripts/ollama-preload.sh`
- Check disk space (models can be several GB)
- For CPU errors: ensure VPS supports AVX2

## 7. ChromaDB issues
- Check health: `curl http://127.0.0.1:8000/api/v2/heartbeat`
- Check volume permissions and free space
- Restart only Chroma: `docker compose restart chroma`

## 8. n8n automations
- Check n8n logs: `docker compose logs n8n`
- Ensure encryption key and BasicAuth are set
- For webhook issues: check URL, firewall, and Nginx proxy

## 9. General tips
- Always check `.env` for missing or incorrect variables
- Use `make` targets for quality and stack management
- For persistent issues, consult `docs/dossier-technique-exhaustif.md` and `CI_ROBUSTESSE.md`
- If all else fails: prune Docker (`docker system prune -af`), reboot VPS, and redeploy

---

For further help, see the full documentation and contact the maintainer.
