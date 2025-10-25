# EPIC Ingestor (multi-sources)
Objectif: Ingestion URL, fichiers (PDF/DOCX/TXT), Google Drive (fileId/dossier), dédup, métadonnées, embeddings via Ollama, stockage Chroma v2.
## Tâches
- [ ] Contrat POST /ingest (source_type in {url,file,gdrive})
- [ ] URL: fetch robuste + extraction texte
- [ ] Fichiers: unstructured (tailles/erreurs)
- [ ] GDrive: service account, scopes, by fileId et folder
- [ ] Dédup: SHA256
- [ ] Chunking: splitters configurables
- [ ] Embeddings: nomic-embed-text, Chroma v2 (collection configurable)
- [ ] Métadonnées: uri, ingest_ts, hints
- [ ] Retours `{status, added, skipped}` + logs clairs
- [ ] Tests: example.com, GDrive public/privé, query v2 ok
