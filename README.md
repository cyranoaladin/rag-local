# RAG – Export (pour GitHub)
- `infra/` : docker-compose, .env.example (sanitisé), vhosts Nginx
- `n8n/`   : workflows JSON, snapshot DB sqlite, webhooks dump
- `src/ingestor/` : FastAPI (si extrait)
- `src/ui/`       : Streamlit (si extrait)
- `ollama-tags.json`, `chroma-heartbeat.http`

## Phase 1 — Ingestion multimodale

- Endpoint `POST /ingest` accepte désormais un fichier (`multipart/form-data`) avec `?mode=text|multimodal`.
- Parsing multimodal encapsulé dans `src/ingestor/mm_adapter.py` (générateur + cache SHA256) avec timeout dur sur RAG-Anything ; fallback texte automatique si dépendances absentes ou lentes.
- Les chunks envoyés à Chroma portent `metadata.modality` (`text|image|table|formula|other`).
- Variables d'environnement clés : `MULTIMODAL_ENABLED`, `MULTIMODAL_PARSER`, `MM_CACHE_DIR`, `MM_PARSER_TIMEOUT`, `INGEST_MAX_FILE_MB`, `MULTIMODAL_DEPS` (cf. `infra/.env.example`). Mettre `MULTIMODAL_DEPS=1` uniquement pour les builds lancés avec le profil `multimodal`.
- Profils Docker supplémentaires : `multimodal` (ingestor avec cache + deps), `multimodal-office` (LibreOffice), `ocr` (tesseract) — inactifs par défaut.
- Tests d'intégration : `tests/test_ingestor_multimodal.py` (skippé si multimodal ou `raganything` désactivés) + `infra/scripts/smoke.sh` pour vérifier PNG/PDF.

```bash
# Après avoir lancé docker compose --profile multimodal
INGESTOR_API_TOKEN=changeme ./infra/scripts/smoke.sh
```

### API côté ingestor

| Route | Méthode | Payload | Cas d'usage |
|-------|---------|---------|-------------|
| `/ingest` | `POST` | `multipart/form-data` (`file`), query `mode=text|multimodal` | upload direct (PDF, PNG, JPG). MIME whitelist stricte. |
| `/ingest/source` | `POST` | JSON historique (`source`, `source_type`, `hints`) | compatibilité n8n / ingestion indirecte (URL, GDrive, chemins locaux, DOCX/PPTX via montages). |
| `/health` | `GET` | — | liveness probe |

### Budgets & observabilité (VPS)

- Mémoire ingestor < 250 MiB par upload (cache disque `/data/cache`).
- Logs JSON : `event=ingest_multimodal`, compteur par modalité, taille en octets.
- `MM_MAX_CHARS_PER_CHUNK=8000` limite les chunks volumineux (tables/images légendées).
- `MM_PARSER_TIMEOUT` (15s par défaut) évite les blocages parse → fallback texte.
