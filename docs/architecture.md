# Architecture RAG locale

Flux principal (texte → réponse) :
1. Client (UI ou CLI) appelle l'ingestor FastAPI.
2. Ingestor valide le token/IP et récupère la source (URL, GDrive, PDF, DOCX).
3. Extraction & nettoyage via loaders LangChain, streaming HTTP contrôlé.
4. Découpage `RecursiveCharacterTextSplitter` (800/120) pour limiter la latence mémoire.
5. Embeddings CPU via Ollama (`nomic-embed-text`) exposé en HTTP local.
6. Déduplication SHA-256 pour éviter les doublons en base.
7. Insertion des chunks + métadonnées normalisées dans Chroma (collection unique).
8. UI Streamlit interroge Chroma (top-k borné) pour récupérer les passages pertinents.
9. Génération finale (hors repo) combine passages avec un LLM (Ollama) pour réponse.

```
[UI/CLI] --HTTP--> [Ingestor FastAPI] --RPC--> [Ollama Embeddings]
                                     \--REST--> [ChromaDB]
                                            \--> [Streamlit UI]
```

Risques de latence/mémoire par étape :
- Téléchargement : streaming HTTP avec plafond `MAX_REMOTE_BYTES` et timeout 30 s (requests).
- Extraction : loaders PDF/DOCX peuvent monter en RAM (~50 MiB) si fichiers volumineux.
- Chunking : taille 800 + overlap 120 limite la duplication ; garder <1500 tokens/chunk.
- Embeddings : Ollama CPU ~150 ms/chunk à chaud ; timeouts bornés par `OLLAMA_REQUEST_TIMEOUT`.
- Chroma : appels REST bornés via `CHROMA_REQUEST_TIMEOUT`; utilisation en lot réduit la pression mémoire.
- UI : cache Streamlit sur client/collection pour éviter reconnections ; top-k ≤ 8.
