# 🔄 PLAN DE MIGRATION — RAG v1 (ChromaDB) → RAG v2 (pgvector)

**Date** : 22 février 2026
**Auteur** : Lead Senior RAG Architect
**Statut** : En cours

---

## 1. FONCTIONS api.py UTILISANT ChromaDB

### Imports ChromaDB (lignes 22-25)
```python
import chromadb
from chromadb.config import Settings
```

### Fonctions directement couplées à ChromaDB

| Fonction | Lignes | Usage ChromaDB | Action v2 |
|----------|--------|----------------|-----------|
| `get_chroma_client()` | 313-323 | Crée `chromadb.HttpClient` avec Settings | **SUPPRIMER** → remplacer par `RagDatabase` (asyncpg) |
| `_index_batch()` | 798-868 | `client.get_or_create_collection()`, `collection.get()`, `collection.add()` | **RÉÉCRIRE** → `db.upsert_document()` + `db.insert_chunks()` |
| `_prepare_chunks_for_chroma()` | 693-734 | Prépare les IDs/docs/metadatas au format ChromaDB | **RENOMMER** → `_prepare_chunks()`, adapter le format pour pgvector |
| `ingest_data()` (POST /ingest) | 951-994 | Appelle `_prepare_chunks_for_chroma` + `_index_batch` | **ADAPTER** → retourner `task_id` (async Celery) |
| `search_kb()` (POST /search) | 1023-1083 | `get_chroma_client()`, `collection.query(query_embeddings=...)` | **RÉÉCRIRE** → `hybrid_search_pipeline()` |
| `rag_query()` (POST /rag/query) | 1100-1179 | `get_chroma_client()`, `collection.query()` avec filtres `where` | **RÉÉCRIRE** → `hybrid_search_pipeline()` avec filtres pgvector |
| `background_drive_ingest()` | 871-948 | Appelle `_prepare_chunks_for_chroma` + `_index_batch` | **ADAPTER** → utiliser Celery task |

### Fonctions dans search_api.py couplées à ChromaDB

| Fonction | Lignes | Usage ChromaDB | Action v2 |
|----------|--------|----------------|-----------|
| `_client_lazy()` | 98-106 | `chromadb.HttpClient` ou `PersistentClient` | **SUPPRIMER** → `RagDatabase` |
| `_embedder_lazy()` | 108-112 | `SentenceTransformerEmbeddingFunction` | **SUPPRIMER** → `EmbeddingService` |
| `_collection()` | 114-115 | `get_or_create_collection` | **SUPPRIMER** |
| `list_collections()` (GET /kb/collections) | 149-170 | `client.list_collections()` | **RÉÉCRIRE** → SQL `SELECT DISTINCT tenant FROM rag_documents` |
| `search()` (POST /kb/search) | 172-245 | `collection.query(query_texts=...)` | **RÉÉCRIRE** → `hybrid_search_pipeline()` |

---

## 2. VARIABLES D'ENVIRONNEMENT ChromaDB À REMPLACER

| Variable actuelle | Valeur actuelle | Remplacement v2 | Nouvelle valeur |
|-------------------|-----------------|------------------|-----------------|
| `CHROMA_HOST` | `chroma` / `localhost` | `PGVECTOR_HOST` | `pgvector` |
| `CHROMA_PORT` | `8000` | `PGVECTOR_PORT` | `5435` |
| `CHROMA_DIR` | `/data/chroma` | *(supprimée)* | — |
| `CHROMA_REQUEST_TIMEOUT` | `30` | *(intégré dans pool asyncpg)* | — |
| `CHROMA_ENFORCE_EMBED_FUNCTION` | `false` | *(supprimée)* | — |
| `CHROMA_RESET_COLLECTION_ON_CONFLICT` | `false` | *(supprimée)* | — |
| `UI_CHROMA_TIMEOUT` | `30` | *(supprimée)* | — |
| `SEARCH_EMBED_MODEL` | `nomic-ai/nomic-embed-text-v1.5` | `EMBED_MODEL` | `nomic-embed-text:v1.5` |

### Nouvelles variables v2

| Variable | Valeur par défaut | Description |
|----------|-------------------|-------------|
| `PGVECTOR_DB` | `ragdb` | Nom de la base PostgreSQL |
| `PGVECTOR_USER` | `raguser` | Utilisateur PostgreSQL |
| `PGVECTOR_PASSWORD` | *(requis)* | Mot de passe PostgreSQL |
| `DATABASE_URL` | `postgresql+asyncpg://...` | DSN async pour l'API |
| `DATABASE_URL_SYNC` | `postgresql://...` | DSN sync pour migrations |
| `REDIS_URL` | `redis://:pass@redis:6379/0` | URL Redis (broker Celery) |
| `REDIS_CACHE_URL` | `redis://:pass@redis:6379/1` | URL Redis (cache embeddings) |
| `REDIS_PASSWORD` | *(requis)* | Mot de passe Redis |
| `EMBED_DIM` | `768` | Dimension des vecteurs |
| `EMBED_CACHE_TTL` | `86400` | TTL cache embeddings (sec) |
| `RERANKER_MODEL` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Modèle de reranking |
| `RERANKER_TOP_N` | `5` | Nombre de résultats reranqués |
| `HYBRID_ALPHA` | `0.7` | Poids dense vs sparse (0-1) |
| `API_SECRET_KEY` | *(requis)* | Clé secrète API (Bearer token) |
| `ALLOWED_TENANTS` | `nsi,nexus,mfai,web3` | Tenants autorisés |
| `IP_ALLOWLIST` | *(vide)* | CIDR autorisés (optionnel) |

---

## 3. ENDPOINTS API — COMPATIBILITÉ

### Endpoints CONSERVÉS (même signature entrée/sortie)

| Endpoint | Méthode | Changement interne |
|----------|---------|-------------------|
| `GET /health` | GET | Ajouter `version: "2.0"`, `vector_store: "pgvector"` |
| `POST /ingest` | POST | Retourne `{"task_id": "...", "status": "pending"}` au lieu du résultat sync |
| `POST /search` | POST | Même format de réponse, mais hybrid search en interne |
| `POST /rag/query` | POST | Même format de réponse |
| `GET /metrics` | GET | Inchangé (Prometheus) |
| `POST /ingest/drive` | POST | Utilise Celery au lieu de BackgroundTasks |
| `GET /admin/health` | GET | Inchangé |
| `POST /admin/documents` | POST | Inchangé |
| `GET /admin/documents` | GET | Inchangé |
| `GET /admin/documents/{id}` | GET | Inchangé |
| `PATCH /admin/documents/{id}` | PATCH | Inchangé |
| `DELETE /admin/documents/{id}` | DELETE | Inchangé |
| `POST /admin/documents/{id}/ingest` | POST | Utilise Celery |
| `GET /admin/documents/{id}/ingestions` | GET | Inchangé |
| `GET /admin/ingestions` | GET | Inchangé |
| `POST /admin/upload` | POST | Inchangé |
| `GET /kb/collections` | GET | SQL au lieu de ChromaDB |
| `POST /kb/search` | POST | Hybrid search |

### Nouveaux endpoints v2

| Endpoint | Méthode | Description |
|----------|---------|-------------|
| `GET /ingest/{task_id}/status` | GET | Statut d'une tâche d'ingestion async |
| `GET /stats/{tenant}` | GET | Statistiques agrégées par tenant |
| `POST /eval/{tenant}` | POST | Lancer évaluation qualité RAG |
| `GET /eval/history/{tenant}` | GET | Historique des évaluations |

---

## 4. RISQUES ET MITIGATIONS

| Risque | Probabilité | Impact | Mitigation |
|--------|-------------|--------|------------|
| Perte de données pendant migration ChromaDB → pgvector | Moyenne | Critique | Script de migration avec vérification de comptage avant/après. Backup ChromaDB avant migration. |
| Incompatibilité dimensions embeddings (768 vs 1536) | Haute | Haute | Colonne `embed_dim` dans `rag_documents`. Re-embedding obligatoire pour les vecteurs OpenAI (1536→768). |
| Régression qualité recherche (dense-only → hybrid) | Faible | Moyenne | Gold set d'évaluation + baseline avant migration. Rollback possible via `HYBRID_ALPHA=1.0` (pure dense). |
| Downtime pendant migration | Moyenne | Moyenne | Migration en parallèle : ChromaDB reste actif pendant que pgvector se remplit. Bascule atomique via variable d'env. |
| Celery worker crash / tâches perdues | Faible | Moyenne | Redis persistence (AOF), retry automatique (max 3), monitoring Prometheus. |
| Clients cassés après changement d'API | Haute | Haute | Compatibilité stricte des endpoints existants. Nouveaux endpoints en plus, pas en remplacement. |
| Secrets exposés dans .env | Déjà présent | Critique | Migration immédiate vers secrets générés + chmod 600 + .gitignore. |

---

## 5. ORDRE D'EXÉCUTION

```
1. [SÉCURITÉ]   Bind ports 127.0.0.1 + régénérer secrets
2. [INFRA]      Créer docker-compose.v2.yml + init.sql + .env.v2
3. [CODE]       Créer database.py, hybrid_search.py, embedding_service.py, tasks.py
4. [TESTS]      Créer tests unitaires + intégration
5. [BUILD]      docker compose -f infra/docker-compose.v2.yml build
6. [UP]         docker compose -f infra/docker-compose.v2.yml up -d
7. [MODELS]     Pull nomic-embed-text:v1.5 dans Ollama
8. [MIGRATE]    Exécuter migrate_chroma_to_pgvector.py (tenant nsi)
9. [MIGRATE]    Exécuter migrate_qdrant_to_pgvector.py (tenant nexus)
10. [EVAL]      Baseline qualité sur gold set
11. [CLIENTS]   Migrer nexus-project_v0, Interface_NSI, journey-simulator
12. [CLEANUP]   Supprimer instances ChromaDB/Qdrant orphelines
13. [PROD]      Déployer sur VPS mf
```
