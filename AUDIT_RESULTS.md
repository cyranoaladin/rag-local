# Rapport d'audit — Projet `rag-local`

## 1. Synthèse du projet

Le projet met en place un pipeline **RAG (Retrieval-Augmented Generation) 100% local** adapté à un déploiement sur un **VPS CPU-only**. L'architecture se compose d'une API FastAPI d'ingestion, d'Ollama pour les embeddings, de ChromaDB comme base vectorielle, d'une interface Streamlit pour la recherche et, en option, d'automations via n8n. L'application est pensée pour une exploitation production-ready avec une stack moderne et cohérente.

Flux de données observé :

1. **Ingestion** : l'interface Streamlit ou n8n transmet des URL ou fichiers locaux à l'API FastAPI (`src/ingestor/api.py`).
2. **Traitement** : l'API nettoie les contenus, découpe en "chunks" et calcule les embeddings via Ollama (`nomic-embed-text`).
3. **Stockage** : vecteurs et métadonnées sont persistés dans **ChromaDB**.
4. **Recherche** : l'interface Streamlit (`src/ui/app.py`) interroge Chroma pour récupérer les chunks pertinents.
5. **Génération (hors dépôt)** : les chunks sélectionnés sont destinés à être envoyés à un LLM (ex. `llama3.2` via Ollama) pour produire la réponse finale.

## 2. Points forts

- **Prêt pour la production** : usage de Docker Compose avec profils (`dev`, `obs`, `smoke`), templates Nginx pour reverse proxy/TLS et scripts de sauvegarde/restauration des volumes.
- **Observabilité** : instrumentation Prometheus (`src/ingestor/metrics.py`) sous feature flag `METRICS_ENABLED` et stack dédiée dans `infra/docker-compose.obs.yml`.
- **Qualité & CI/CD** : suite de tests (`tests/`), workflows GitHub Actions (`.github/workflows/ci.yml`) et tooling lint/typecheck (Ruff, Mypy) via `pyproject.toml`.
- **Sécurité** : API d'ingestion protégée par token `X-API-Token`, allowlist IP (`INGESTOR_IP_ALLOWLIST`) et protections anti-SSRF.
- **Documentation** : `SPEC.md`, `README-PROD.md`, `ops-checklist.md`, `architecture.md` fournissent un cadran clair pour déploiement et maintenance.

## 3. Axes d'amélioration

### A. Ingestor (API FastAPI)

- **Extraction DOCX limitée** : `load_docx` ne lit que les paragraphes simples et ignore tableaux/entêtes/pieds. -> **Action** : utiliser `unstructured` (déjà listé) ou enrichir pour parcourir tables et autres éléments complexes.
- **Cache multimodal non persistant** : `mm_adapter.py` écrit dans `MM_CACHE_DIR` mais le chemin n'est pas monté comme volume dans `docker-compose.yml`. -> **Action** : monter un volume persistant pour `MM_CACHE_DIR` afin de conserver le cache entre redémarrages.
- **Timeouts clients manquants** : `chromadb.HttpClient` et `OllamaEmbeddings` sont instanciés sans timeout explicite. -> **Action** : définir des timeouts configurables pour éviter qu'une dépendance bloquée ne fige l'API.

### B. UI (Streamlit)

- **Ergonomie** : la page expose deux formulaires d'ingestion (n8n et API directe) qui peuvent prêter à confusion. -> **Action** : séparer clairement la partie administration (API directe) du flux utilisateur standard.
- **Sécurité** : l'ingestion directe affiche un champ token. La documentation rappelle la nécessité du Basic Auth Nginx (`UI_BASIC_AUTH_*`) mais il faut insister sur son caractère obligatoire.

### C. Documentation & fichiers

- **README.md** : la section "Contrat des métriques (Prometheus)" apparaît deux fois (dont un ajout récent visible dans `patch-readme-metrics.diff`). -> **Action** : fusionner/dé-dupliquer la section.
- **AUDIT_CHECKLIST.md** : l'ancien `AUDIT.md` est une checklist/prompt pour préparer un audit. -> **Action** : conserver cette checklist et utiliser `AUDIT_RESULTS.md` pour consigner les comptes rendus.

### D. Tests & qualité

- **Couverture UI** : aucun test ne couvre `src/ui/app.py`. -> **Action** : ajouter au minimum des tests unitaires pour les fonctions non graphiques (`_call_webhook`, `_call_ingest_api`) en mockant `requests`.

## 4. Priorités recommandées

1. **Sécuriser l'UI** : s'assurer que le Basic Auth Nginx protège l'interface avant toute mise en production.
2. **Cache multimodal** : décider si le cache doit persister et, le cas échéant, monter un volume dédié.
3. **Ingestion DOCX** : enrichir le parser pour capturer tableaux et métadonnées structurées.
4. **Nettoyage & tests** : dédupliquer le `README.md` et compléter la couverture de tests côté UI.
