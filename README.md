# RAG – Export (pour GitHub)
- `infra/` : docker-compose, .env.example (sanitisé), vhosts Nginx
- `n8n/`   : workflows JSON, snapshot DB sqlite, webhooks dump
- `src/ingestor/` : FastAPI (si extrait)
- `src/ui/`       : Streamlit (si extrait)
- `ollama-tags.json`, `chroma-heartbeat.http`

## Metrics disponibles (/metrics)

| Nom | Type | Labels | Unité | Description |
| --- | --- | --- | --- | --- |
| `rag_local_ingest_requests_total` | Counter | `route`, `method` | requêtes | Volume de requêtes HTTP reçues par l’ingestor. |
| `rag_local_ingest_success_total` | Counter | `modality` | ingests | Ingestions abouties (texte, multimodal). |
| `rag_local_ingest_failure_total` | Counter | `reason` | erreurs | Erreurs fonctionnelles/techniques normalisées. |
| `rag_local_ingest_chunks_total` | Counter | `modality` | chunks | Chunks écrits dans Chroma (texte ou multimodal). |
| `rag_local_ingest_bytes_total` | Counter | – | octets | Octets persistés dans la collection. |
| `rag_local_ingest_latency_seconds` | Histogram | `route` | secondes | Latence des routes /ingest et dérivées. |
| `rag_local_mm_parse_latency_seconds` | Histogram | – | secondes | Temps passé dans l’adapter multimodal. |
| `rag_local_mm_chunks_total` | Counter | `modality` ∈ {text,image,table,formula,other} | chunks | Chunks multimodaux émis par l’adapter. |
| `rag_local_mm_bytes_total` | Counter | `modality` | octets | Volume traité par modalité lors du parsing. |
| `rag_local_mm_parse_failures_total` | Counter | `reason` | erreurs | Défaillances détectées dans le parsing multimodal (ex: timeout). |

## Observabilité multimodale

1. Activer le parsing multimodal via l’environnement :

	```dotenv
	MULTIMODAL_ENABLED=true
	MM_PARSER_TIMEOUT=60        # secondes (0 force le fallback texte)
	MM_MAX_CHARS_PER_CHUNK=4000 # borne RAM du fallback
	MM_CACHE_DIR=/tmp/rag-mm-cache
	```

2. Relancer l’ingestor (`docker compose --profile api restart ingestor`).
3. Vérifier les métriques : `curl http://localhost:8001/metrics | grep mm_`.

En cas de dépassement de `MM_PARSER_TIMEOUT`, l’adapter retombe automatiquement sur un chunk texte minimal et incrémente `mm_parse_failures_total{reason="timeout"}` pour faciliter le diagnostic.
