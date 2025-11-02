# rag-local — Dossier technique exhaustif

## 1. Finalité et périmètre
- Solution RAG locale prête pour VPS CPU-only : ingestion de ressources pédagogiques, indexation vectorielle, consultation via UI ou automatisations.
- Cible : lycées/enseignants. Contraintes principales : faible RAM, aucune dépendance GPU, exposition publique uniquement via Nginx.
- Modules principaux : ingestor FastAPI, base ChromaDB, moteur d'embeddings Ollama, UI Streamlit, orchestrations n8n, observabilité Prometheus optionnelle.

## 2. Vue d'ensemble fonctionnelle
```
[Sources humaines / n8n] --HTTP--> [FastAPI Ingestor]
                               |--RPC--> [Ollama embeddings]
                               '--REST--> [ChromaDB collection]
[Streamlit UI] ---query---> [ChromaDB]
                    '--(LLM externe facultatif)-->
[Utilisateurs finaux] <= réponses contextuelles (texte + métadonnées)
```
- Flux ingestion : sécurisation (token + allowlist), téléchargement/lecture, chunking, embeddings, insertion dédupliquée.
- Flux interrogation : UI calcule top-k sur Chroma, affiche extraits et métadonnées, peut déclencher n8n ou LLM.
- Multimodal : ingestion vidéo/doc binaire via parseur `mm_adapter` (cache disque, timeouts, labels de modalité).

## 3. Arborescence du dépôt
```
.
├── docs/                     # Documentation d'architecture, observabilité, opérations, audit
├── infra/                    # Docker Compose, .env, scripts d'exploitation, nginx, data uploads
│   ├── docker-compose*.yml   # Pile principale, profils dev/obs/smoke
│   ├── nginx/                # Templates envsubst + rendu
│   ├── scripts/              # smoke, backup, restore, metrics quickcheck, ollama preload
│   └── data/uploads/         # Zone blanche pour fichiers à ingérer (montée en volume)
├── src/
│   ├── ingestor/             # API FastAPI + parseur multimodal + métriques + Dockerfile
│   └── ui/                   # Application Streamlit + Dockerfile
├── tests/                    # Tests FastAPI (sécurité, chunking, métriques)
├── Makefile                  # Cibles lint/type/test/smoke/obs
├── requirements*.txt         # Dépendances runtime et dev
├── pyproject.toml            # Configuration ruff/mypy/pylint
└── README*.md, SPEC.md       # Guides d'exploitation et spécifications
```

## 4. Services et conteneurs
| Service   | Image / Build                     | Profil Compose     | Ports (prod) | Rôle principal |
|-----------|-----------------------------------|--------------------|--------------|----------------|
| `chroma`  | `chromadb/chroma:1.1.1`           | `db`               | interne      | Stockage vecteurs + métadonnées (collection `ressources_pedagogiques_terminale`). |
| `ollama`  | `ollama/ollama:0.3.13`            | `llm`              | interne      | Embeddings `nomic-embed-text`, petit LLM `llama3.2`. |
| `ingestor`| build `src/ingestor` (FastAPI)    | `api`              | interne      | Endpoints `/ingest`, `/health`, `/metrics` (optionnel). |
| `ui`      | build `src/ui` (Streamlit)        | `ui`               | interne      | Tableau de bord ingestion + requêtes. |
| `n8n`     | `n8nio/n8n:stable`                | `automations`      | interne      | Orchestrations ingestion (webhooks, planifications). |
| `web`     | `nginx:1.27-alpine`               | `web`              | interne      | Reverse proxy HTTP/TLS, sécurisation et terminason. |
| `prometheus` (optionnel) | `prom/prometheus` | `obs`              | interne      | Scrape métriques ingestor si profil activé. |

- **Réseau** : bridge `rag_net` commun aux services ; exposition extérieure conditionnée par templates Nginx ou overrides dev.
- **Volumes persistants** : `rag_chroma_data`, `rag_ollama_data`, `rag_n8n_data`, `rag_prometheus_data` (obs). Fichiers uploadés montés depuis `infra/data/uploads`.
- **Sécurité conteneurs** : ingestor/ui en lecture seule (`read_only: true`), `tmpfs` pour `/tmp`, `no-new-privileges`, limites CPU/RAM définies.
- **Profils Compose** contrôlent la surface démarrée selon contexte (`COMPOSE_PROFILES`).

## 5. Backend d'ingestion (FastAPI — `src/ingestor/api.py`)
### 5.1 Endpoints
| Route        | Méthode | Description | Auth |
|--------------|---------|-------------|------|
| `/ingest`    | POST    | Ingestion sources (`url`, `gdrive_folder`, `pdf`, `docx`, `markdown`, `md`, `video`). Paramètre `mode` (`text` par défaut, `multimodal` requis pour vidéo). Retour JSON `{"status":"ok","added":n,"skipped":m}`. | Header `X-API-Token` (ou valeur `INGEST_AUTH_HEADER`) obligatoire si `INGESTOR_API_TOKEN` défini + filtrage IP CIDR via `INGESTOR_IP_ALLOWLIST`. |
| `/health`    | GET     | Vérification de vivacité (latence cible <100 ms). | Public (réseau interne). |
| `/metrics`   | GET     | Expose Prometheus si `METRICS_ENABLED=true`; 404 sinon. | Interne, passerelle Nginx recommandée. |

### 5.2 Pipeline d'ingestion
1. **Sécurité** : `_enforce_security` vérifie token et IP (parse `X-Forwarded-For`).
2. **Chargement source** :
   - `url` → téléchargement HTTP avec anti-redirect interne, contrôle `MAX_REMOTE_BYTES`, conversion HTML→texte (`BeautifulSoup`).
   - `pdf`/`docx`/`markdown` → lecture locale dans `LOCAL_SOURCE_ROOT`, validation du chemin, gestion d'encodage.
   - `gdrive_folder` → `GoogleDriveLoader` (dépend d'un compte de service monté sous `/creds`).
   - `video` → mode multimodal obligatoire (voir §6).
3. **Chunking texte** : `RecursiveCharacterTextSplitter` (taille configurable `INGEST_CHUNK_SIZE`, overlap `INGEST_CHUNK_OVERLAP`).
4. **Normalisation métadonnées** : fusion hints, métadonnées loader, ajout `sha256`, `source_type`, `modality`; normalisation en snake_case.
5. **Déduplication** : calcul sha256, interrogation Chroma pour éviter doublons.
6. **Embeddings** : `OllamaEmbeddings` (base_url `OLLAMA_URL`). Gestion d'erreurs : HTTP 404 → message explicite sur modèle manquant.
7. **Insertion Chroma** : `get_or_create_collection` avec `hnsw:space=cosine`, ajout documents, métadonnées, embeddings.
8. **Métriques** : compteurs succès/échec, histogrammes latence, résultats par type/modality/status.

### 5.3 Gestion des erreurs et timeouts
- `requests.get` sur contenus distants avec `timeout=30`, streaming pour limiter mémoire.
- Interdiction des IP privées/loopback/multicast sur URL distantes.
- Taille max cumulée `MAX_REMOTE_BYTES` (def 10 MiB). Dépassement → HTTP 400.
- `HTTPException` 503 si modèle embeddings absent, 500 sur erreurs interne Chroma/Ollama.

### 5.4 Variables d'environnement clés
| Nom | Rôle |
|-----|------|
| `CHROMA_HOST` / `CHROMA_PORT` | Adresse du service Chroma. |
| `OLLAMA_URL` / `EMBED_MODEL`  | Endpoint embeddings et modèle Ollama. |
| `LOCAL_SOURCE_ROOT`           | Racine autorisée pour fichiers locaux (`/data/uploads`). |
| `MAX_REMOTE_BYTES`            | Plafond taille téléchargements distants. |
| `INGESTOR_API_TOKEN`          | Jeton obligatoire (`INGEST_AUTH_HEADER` personnalisé possible). |
| `INGESTOR_IP_ALLOWLIST`       | Liste CIDR autorisées (ex: `127.0.0.1/32,10.0.0.0/8`). |
| `MULTIMODAL_ENABLED`, `MM_*`  | Activation et réglages parseur multimodal (timeout, chunk size, cache). |
| `CHROMA_REQUEST_TIMEOUT` / `OLLAMA_REQUEST_TIMEOUT` | Timeouts réseau (s) pour Chroma et Ollama côté ingestor. |
| `UI_CHROMA_TIMEOUT` / `UI_INGEST_TIMEOUT` | Timeouts utilisés par l'interface Streamlit (Chroma et API). |
| `METRICS_ENABLED`, `METRICS_NAMESPACE` | Pilotage export Prometheus. |

## 6. Adapter multimodal (`src/ingestor/mm_adapter.py`)
- Lit fichiers binaires (vidéo, JSON, etc.) en streaming contrôlé, calcule hash+mtime pour clé de cache.
- Cache JSON persistant sous `MM_CACHE_DIR` (par défaut `/data/mm-cache`, volume Docker nommé `rag_mm_cache`).
- Émet des `Chunk` avec `modality`, texte ou blob, métadonnées (index, filename, mime, cached, parse_timeout).
- Instrumentation métrique : latence parsing (`rag_local_mm_parse_latency_seconds`), compte chunks/bytes, erreurs (timeout, payload vide).
- Fallback : si parseur dépasse `MM_PARSER_TIMEOUT`, enregistre échec et retourne texte brut ou blob.

## 7. Métriques et observabilité (`src/ingestor/metrics.py`)
- `CollectorRegistry` isolé pour tests, gating global `METRICS_ENABLED` (par défaut `true`).
- Compteurs : `*_ingest_requests_total`, `*_ingest_success_total`, `*_ingest_failure_total`, `ingest_requests_total` (labels `source`, `modality`, `status`).
- Histogrammes : latence requêtes (`ingestor_request_latency_seconds`), parsing multimodal.
- Helpers context managers (`track_latency`, `track_mm_parse_latency`) utilisés dans middleware et parseur.
- Endpoint `/metrics` renvoie 404 si métriques désactivées (aligné avec tests `test_metrics_gating.py`).

## 8. Base vectorielle (Chroma)
- Conteneur `chromadb/chroma:1.1.1`, persistance `rag_chroma_data`.
- Variables `IS_PERSISTENT=TRUE`, `ANONYMIZED_TELEMETRY=FALSE`.
- Collection unique par défaut `ressources_pedagogiques_terminale`.
- Insertion via API HTTP v2 ; healthcheck `GET /api/v2/heartbeat`.
- Requêtes UI : `collection.query(query_texts=[...], n_results=k)` renvoie documents, métadonnées, distances.

## 9. Embeddings / LLM (Ollama)
- Image `ollama/ollama:0.3.13`, écoute 11434 (interne).
- Modèles préconisés : `nomic-embed-text` (embeddings), `llama3.2:latest` (génération optionnelle).
- Script `infra/scripts/ollama-preload.sh` pour pré-télécharger modèles (lit `OLLAMA_PRELOAD_MODELS`).
- Ressources limites : `cpus: 6`, `memory: 24G` (prod), overrides CI réduisent à 3.5 vCPU / 12G.

## 10. UI Streamlit (`src/ui/app.py`)
- Pages : onglets "Via n8n" (flux standard) et "Administration API" (ingestion directe) + explorateur Chroma.
- Lancement contrôlé : `STREAMLIT_IMPORT_ONLY=1` pour import sans rendu (tests). `render_app()` appelé sinon.
- `st.cache_resource` pour client Chroma (avec `Settings` + timeout), `st.cache_data` pour compteur documents (TTL 30s).
- Paramètres ingestion : hints (matière, voie, niveau, type, année) fusionnés côté API.
- Support multimodal : source `video` affiche avertissement et impose `mode=multimodal`.
- Appels API : `requests.post` avec `INGEST_AUTH_HEADER` configurable, timeouts (`UI_INGEST_TIMEOUT`, `UI_CHROMA_TIMEOUT`).
- Recherche : slider `k` (borne `UI_MAX_K`, par défaut 8). Résultats affichent texte + dataframe métadonnées.
- Sécurité : onglet "Administration" rappelle d'activer le Basic Auth Nginx.

## 11. Automatisations n8n (`n8n/`)
- Image `docker.n8n.io/n8nio/n8n:stable` avec BasicAuth et clé d'encryption.
- Webhooks déportés (exemples sous `n8n/workflows/examples/`).
- Variables nécessaires :
  - `N8N_BASIC_AUTH_ACTIVE`, `N8N_BASIC_AUTH_USER`, `N8N_BASIC_AUTH_PASSWORD`.
  - `N8N_ENCRYPTION_KEY`, `N8N_EXTERNAL_DOMAIN`.
- Service dépend du `ingestor` (healthcheck `/healthz`).

## 12. Reverse proxy Nginx (`infra/nginx/`)
- Templates `rag-ui.conf.template`, `rag-n8n.conf.template` rendus via `envsubst`.
- Headers sécurité intégrés : `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options`, `Permissions-Policy`, CSP minimaliste. HSTS commenté jusqu'à disponibilité TLS.
- Variables dynamiques : `NGINX_*`, directives BasicAuth injectées (`UI_BASIC_AUTH_DIRECTIVE`, `N8N_BASIC_AUTH_DIRECTIVE`).
- `infra/nginx/nginx.conf` : configuration globale (logs sur stdout/stderr, `server_tokens off`).

## 13. Déploiement et environnements (`infra/.env*.sample`)
- `infra/.env.example` : base dev/preprod (tokens placeholders, allowlist vide par défaut, `METRICS_ENABLED=false`).
- `infra/.env.production.sample` : valeurs réalistes (allowlist RFC1918, `METRICS_ENABLED=true`, `MM_CACHE_DIR=/data/mm-cache`).
- `COMPOSE_PROFILES` par défaut `db,llm,api,ui,automations,web`; personnalisation possible selon contexte.
- Scripts de gestion :
  - `make compose-up` / `make compose-down` (via wrappers Makefile si présents).
  - `infra/scripts/smoke.sh` : démarre stack minimale, vérifie santé, assure modèle embeddings, effectue ingestion de test.
  - `infra/scripts/metrics_quickcheck.sh` : valide Prometheus + endpoint `/metrics`.
  - `infra/scripts/backup-volumes.sh` / `restore-volumes.sh` : sauvegarde/restauration volumes Docker (`busybox` + `tar`).

## 14. Observabilité
- Profil `obs` ajoute Prometheus (`infra/docker-compose.obs.yml`), exposé en localhost 19090 via override.
- `docs/observability.md` décrit métriques, scrapes, alertes recommandées (ingest échecs, p99 latence >4s).
- Healthchecks Compose :
  - `chroma` (req HTTP `/heartbeat`).
  - `ollama` (HTTP `/api/tags`).
  - `ingestor` (script Python `urllib` sur `/health`).
  - `ui` (probe HTTP 200).
  - `n8n` (wget `/healthz`).
  - `web` (nginx -t + GET loopback).
  - `prometheus` (wget health endpoints).

## 15. Sécurité applicative
- **Auth ingestion** : header token obligatoire (nom configurable), IP allowlist (CIDR multiples). Rejet 401/403 testé (`tests/test_ingestor_security.py`).
- **Téléchargements distants** :
  - Schémas autorisés : HTTP/HTTPS.
  - Résolution DNS puis filtrage IP (interdit private/link-local/loopback/multicast/reserved).
  - Plafond taille cumulée, suivi redirects.
  - User-Agent configurable (`USER_AGENT`).
- **Fichiers locaux** : chemin résolu, restreint à `LOCAL_SOURCE_ROOT` sauf override explicite (`ALLOW_UNRESTRICTED_LOCAL`).
- **UI** : peut exiger BasicAuth via Nginx ; ne stocke pas de secrets côté client (token mis dans header seulement lors appel).
- **n8n** : BasicAuth + TLS via Nginx (certbot recommandé). Télémetry désactivée.
- **Logs** : driver json-file limité `max-size=10m` / `max-file=5`.

## 16. Pipelines qualité & CI/CD
- `Makefile` : `lint` (ruff), `typecheck` (mypy), `test` (pytest), `smoke` (script), `obs-*` (pile observabilité).
- `requirements-dev.txt` installe runtime + outils QA (ruff, mypy, pytest, pytest-mock, httpx, pylint, stubs types).
- `pyproject.toml` : ruff (E,F,I,UP,B), mypy (Python 3.11, `ignore_missing_imports`), pylint (docstrings optionnels).
- GitHub Actions (`.github/workflows/ci.yml`) : lint, mypy, pytest (Py 3.10 / 3.11), artefacts ruff/pytest. Job `smoke-compose` optionnel.
- Tests clés :
  - `test_ingestor_security.py` : token obligatoire, allowlist, stubs dépendances.
  - `test_ingestor_unit.py` : chunking, succès ingestion, métriques.
  - `test_metrics*` : gating `/metrics`, singleton registre.

## 17. Dépendances
- **Ingestor** : FastAPI, Uvicorn, LangChain (chargers/embeddings), Chroma client HTTP, Ollama SDK, Unstructured (parsing PDF/Markdown), Prometheus client, BeautifulSoup4, Requests, Python-Docx, Python-Multipart.
- **UI** : Streamlit, Requests, Chroma client, Pandas.
- **Dev** : Ruff, Mypy, Pytest + plugins, Pylint, Httpx (tests), stubs type libs, Prometheus client (tests).
- Politique : aucune dépendance GPU ; extras multimodaux gardés lean.

## 18. Workflows d'utilisation
### 18.1 Ingestion via webhook n8n
1. Utilisateur remplit formulaire UI (`source`, `source_type`, `hints`).
2. UI POST JSON vers webhook n8n (`_call_webhook`).
3. Workflow n8n déclenche ingestion (non fournie ici, JSON exemples dans `n8n/workflows/examples`).

### 18.2 Ingestion directe
1. UI envoie POST `/ingest` au service FastAPI (token, hints, mode).
2. API effectue pipeline décrit §5.
3. Réponse affichée dans UI + journaux compose.

### 18.3 Recherche utilisateur
1. UI appelle `collection.query` avec texte question, `k` (borne 8 par défaut).
2. Résultats triés par distance ; UI affiche extraits, métadonnées tabulées.
3. Option d'exploiter LLM externe (hors périmètre repo) avec passages renvoyés.

### 18.4 Multimodal
1. Développeur place vidéo/fichier dans `infra/data/uploads/`.
2. POST `/ingest` `mode=multimodal`, `source_type=video`, `source` chemin local.
3. `mm_adapter` segmente, cache via hash, alimente Chroma avec `modality` (`text`, `image`, etc.).

## 19. Scripts et opérations
- `infra/scripts/smoke.sh` : stack up (profils `db,llm,api`), health watchers, curl `/ingest` (url example.com), ensures Ollama modèle (pull si absent). Fournit logs en cas d'échec.
- `infra/scripts/metrics_quickcheck.sh` : checks Prometheus readiness, attrape `/metrics`, exécute requête PromQL de base.
- `infra/scripts/backup-volumes.sh` : archive `.tgz` volumes cibles (utilise conteneur busybox).
- `infra/scripts/restore-volumes.sh` : restauration (vidage volume puis extraction archive).
- `infra/scripts/ollama-preload.sh` : démarre `ollama`, télécharge liste modèles fournie.
- `scripts/smoke.sh` (racine) : wrapper pour environnements hors `infra`.

## 20. Points de vigilance et recommandations
- **Ressources** : ingestion multimodale peut accroître usage CPU/RAM ; respecter budgets (ingestor ≤ 250 MiB, UI ≤ 200 MiB). Ajuster `MM_PARSER_TIMEOUT`, `MM_MAX_CHARS_PER_CHUNK`.
- **Sécurité réseau** : vérifier allowlist avant production ; ne jamais exposer ports Compose directement en prod (profil `web` sans `ports`).
- **Secrets** : générer tokens forts (`openssl rand -hex 32`). Garder `infra/creds` hors VCS.
- **Modèles Ollama** : prévoir espace disque (~3 Go pour `nomic-embed-text`), vérifier compat CPU (AVX2 recommandé).
- **Backups** : planifier rotation backups volumes et dossiers `infra/data/uploads`, `infra/creds`.
- **Monitoring** : activer `METRICS_ENABLED` en prod, configurer Prometheus+Alertmanager. Surveiller `ingest requests total` statuts ≠ success.
- **Chunking** : paramètres actuels 800/120 adaptés à compromis rappel/latence ; possibilité de réduire (ex. 600/80) si latence critique, documenter.
- **Testing** : exécuter `make lint typecheck test smoke` avant déploiements. Smoke script suppose ports dev (18001/18501) bouclés.

## 21. Annexes utiles
### 21.1 Ports & exposition
default mapping (dev overrides)
| Service   | Port interne | Override dev | Exposition prod |
|-----------|--------------|--------------|-----------------|
| chroma    | 8000         | —            | Interne (via Nginx ou UI). |
| ollama    | 11434        | —            | Interne uniquement. |
| ingestor  | 8001         | `127.0.0.1:18001` | Interne, proxifié via Nginx. |
| ui        | 8501         | `127.0.0.1:18501` | Interne, proxifié via Nginx. |
| n8n       | 5678         | —            | Interne, proxifié via Nginx. |
| nginx     | 80/443       | `127.0.0.1:18080` (dev) | Seul point d'entrée public. |
| prometheus| 9090         | `127.0.0.1:19090` (obs) | Interne, accès ops. |

### 21.2 Commandes clés
- **Local dev** :
  ```bash
  python -m venv .venv && source .venv/bin/activate
  pip install -r requirements-dev.txt
  cp infra/.env.example infra/.env
  make compose-up
  bash infra/scripts/smoke.sh
  ```
- **QA** : `make lint && make typecheck && make test`.
- **Observabilité** : `make obs-up`, `make obs-quickcheck`.
- **Déploiement prod** :
  ```bash
  cp infra/.env.production.sample infra/.env
  docker compose -f infra/docker-compose.yml --env-file infra/.env up -d
  envsubst < infra/nginx/rag-ui.conf.template > infra/nginx/rendered/rag-ui.conf
  envsubst < infra/nginx/rag-n8n.conf.template > infra/nginx/rendered/rag-n8n.conf
  # Déployer les fichiers rendus sur le reverse proxy public + certbot
  ```

Ce dossier couvre l'intégralité des aspects techniques du projet rag-local : architecture, opérations, sécurité, dépendances et procédures. Il fournit à un auditeur externe toutes les informations nécessaires pour comprendre, valider et maintenir la solution sans consultation préalable du code.
