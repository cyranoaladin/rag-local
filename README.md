# RAG – Export (pour GitHub)
- `infra/` : docker-compose, .env.example (sanitisé), vhosts Nginx
- `n8n/`   : workflows JSON, snapshot DB sqlite, webhooks dump
- `src/ingestor/` : FastAPI (si extrait)
- `src/ui/`       : Streamlit (si extrait)
- `ollama-tags.json`, `chroma-heartbeat.http`
