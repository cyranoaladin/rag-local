# Admin API

Auth: `Authorization: Bearer <token>` (ou `X-API-Token: <token>`). Même jeton que `/ingest`.

Base path: `/admin`

## Documents

- POST `/admin/documents`
  - Crée un document logique (domain, source_type, source_location, title?, tags?, metadata?)
- GET `/admin/documents`
  - Liste des documents (filtre `domain` optionnel)
- GET `/admin/documents/{id}`
  - Détail du document
- PATCH `/admin/documents/{id}`
  - Met à jour uniquement: `title`, `tags`, `metadata`
  - `domain`, `source_type`, `source_location` sont immuables
- DELETE `/admin/documents/{id}`
  - Supprime le document (cascade sur `ingestion_runs`)
- GET `/admin/documents/{id}/ingestions`
  - Historique des ingestions du document
- POST `/admin/documents/{id}/ingest`
  - Orchestration: crée un `ingestion_run` + POST `/ingest` avec les métadonnées enrichies (`domain`, `document_id`, ...)

## Ingestions globales

- GET `/admin/ingestions?document_id=&status=&since=&limit=`
  - Liste les `ingestion_runs` globalement avec filtres optionnels

## Upload

- POST `/admin/upload` (multipart/form-data)
  - Champs: `file`
  - Params:
    - `ingest` (bool, défaut false): déclenche ingestion après upload
    - `document_id` (optionnel): si absent et `ingest=true`, un document est créé
    - `domain` (requis si création)
    - `title`, `tags` (JSON array), `metadata` (JSON object)
  - Réponse: `{ path, filename, size_bytes, mime, source_type_guess }`

Exemples

```bash
# Créer un document (markdown)
curl -sS -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"domain":"lycee","source_type":"markdown","source_location":"/data/uploads/doc.md","title":"Chapitre"}' \
  https://$RAG_API/admin/documents | jq .

# Upload + ingestion immédiate
echo "# Cours" > /tmp/cours.md
curl -sS -X POST "https://$RAG_API/admin/upload?ingest=true&domain=lycee&title=COURS" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/tmp/cours.md" | jq .

# Ingestions globales
curl -sS -H "Authorization: Bearer $TOKEN" "https://$RAG_API/admin/ingestions?limit=20" | jq .
```
