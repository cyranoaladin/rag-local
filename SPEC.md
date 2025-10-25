
# rag-local — Spécification Fonctionnelle & Technique

## 1. Objectifs

* RAG **local**, autonome (embeddings/LLM via **Ollama**), déployable sur **VPS**.
* Ingestion **multi-sources** : fichiers, URLs, Google Drive (service account).
* **UI** de recherche et **API** d’ingestion robustes.
* Opérations simples (compose), sans dépendances cloud fermées.

## 2. Parcours & Rôles

* **Admin OPS** : déploie, configure, sauvegarde/restaure, surveille.
* **Admin Contenu** : déclenche les ingestions (upload, URL, GDrive), tague avec des métadonnées.
* **Utilisateur final** : recherche dans l’UI.

## 3. Exigences Fonctionnelles (extraits)

### 3.1 Ingestion

* **Endpoint** `POST /ingest` (Ingestor FastAPI) :

  * `source_type`: `url` | `gdrive` | `file` (ou `path` via volume).
  * `source`: URL, ID GDrive, ou chemin/fichier uploadé.
  * `hints` (dict libre) : ex. `matiere`, `niveau`, `document_type`, `annee_programme`.
  * Réponse : `{ "status":"ok", "added":<int>, "skipped":<int> }`.
* Deduplication basique (hash contenu).
* Split intelligent (langchain text splitters).
* Embeddings via `nomic-embed-text` (768d), stockage dans **Chroma v2**, collection par défaut : `ressources_pedagogiques_terminale` (configurable).
* Support MIME : PDF, DOCX, HTML, TXT, etc. (via `unstructured`).

### 3.2 Recherche (UI)

* Champ texte, top-k (par défaut 3-5).
* Affichage source + extrait + métadonnées.
* Prévoir un bouton “Re-indexer” (optionnel).

### 3.3 Orchestration (n8n)

* Workflows exportés versionnés (`n8n/workflows/wf/*.json`).
* Scénarios : “ingérer un dossier GDrive”, “ingestion URL régulière”, etc.

## 4. API (contrats)

### 4.1 `GET /health`

* 200 si **Ingestor** prêt.

### 4.2 `POST /ingest`

* Body JSON :

```json
{
  "source": "https://exemple.com/",
  "source_type": "url",
  "hints": { "matiere": "NSI", "niveau": "terminale" }
}
```

## 5. Données & Métadonnées

* **Chroma v2** (HTTP) — Collections : nom logique (par défaut `ressources_pedagogiques_terminale`).
* Métadonnées stockées aux côtés des documents (hints + `uri`, `ingest_ts`, etc.).
* **Attention** : utilisez **/v2/tenants/default_tenant/databases/default_database/** pour l’API REST.

## 6. Modèles & Paramètres

* **Embeddings** : `nomic-embed-text:latest` (CPU).
* **LLM** : `llama3.2:latest` (CPU).
* Variables via `infra/.env`.

## 7. Observabilité

* Healthchecks docker.
* Logs via `docker compose logs`.
* Option d’export OpenTelemetry (désactivée par défaut).

## 8. Sécurité

* n8n protégé par Basic Auth.
* Ollama/Chroma non exposés publiquement (loopback uniquement via Nginx → UI/Ingestor).
* Pas de secrets commités (voir `.gitignore`).

## 9. Performance & Limites

* CPU-only par défaut (suffisant pour PoC/usage léger).
* Chunk size/splitter ajustables (trade-off qualité/latence).
* GDrive : veillez aux quotas API et aux permissions de partage.

## 10. Roadmap (extraits)

* Upload fichiers direct UI.
* Multi-collections (par niveau/matière).
* AuthN UI (reverse-proxy + SSO, optionnel).
