# Knowledge Base API (external)

This API allows external agents/services to search the knowledge base built by rag-local.

Base URL (behind Nginx in production):
- https://$RAG_API_EXTERNAL_DOMAIN

Authentication
- Use Authorization: Bearer $INGESTOR_API_TOKEN (same token as ingestion)
- Alternatively, X-API-Token: $INGESTOR_API_TOKEN

Search
- POST /search
- Body:
```json
{
  "q": "your query string",
  "k": 6,
  "include_documents": true,
  "collection": "ressources_pedagogiques_terminale"
}
```
- Response (example):
```json
{
  "query": "your query string",
  "collection": "ressources_pedagogiques_terminale",
  "k": 6,
  "hits": [
    {
      "id": "<sha256>",
      "metadata": {"source": "https://example.com", "modality": "text", "sha256": "..."},
      "document": "chunk text...",
      "score": 0.12
    }
  ]
}
```

Notes
- k is clamped to [1, 50]
- score is a distance (cosine); lower is better
- include_documents=false returns only ids and metadata
- The collection defaults to the deployed one; multi-tenant setups can customize this in future iterations
