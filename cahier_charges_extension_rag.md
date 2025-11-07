Multi-tenants, agents externes, persistance VPS (exécuter maintenant)

Contexte non négociable

Tout est auto-hébergé sur le VPS, sans dépendance cloud : DB SQLite persistée sur disque, Chroma/Ollama locaux.

Deux verticaux/tenants :

edu (accompagnement scolaire Lycée : doc_type, domain, level, matiere, track)

web3 (plateforme blockchain/web3 : PAS de level/matiere ; taxonomie = topic, chain, tool, difficulty {beginner|intermediate|advanced}).

Accès externe requis : créer des dossiers, ingérer (dans nouveaux ou existants), consulter (search RAG read-only), suivre jobs.

Sécurité : header X-API-Key obligatoire, scopes par clé, CORS dynamiques par clé, rate-limit par clé.

SSE pour le suivi jobs (pas de polling).

Prometheus : compteurs/latences pour /admin/*, /ingest, /kb/*, /jobs/*.

0) Choix & arborescence (appliquer maintenant)

Persistance : ADMIN_DB_PATH=/srv/rag-admin/admin.db (crée le répertoire si absent).

Code :

src/admin/models.py (SQLAlchemy + Alembic-lite),

src/admin/service.py (helpers CRUD + cache/mutex),

src/admin/router.py (FastAPI router /admin/*),

src/common/auth.py (API keys, scopes, CORS par clé),

src/common/ratelimit.py (token-bucket mémoire),

src/common/sse.py (EventSource text/event-stream),

examples/api_keys.sample.json (ne jamais commiter api_keys.json réel).

Variables .env:

ADMIN_DB_PATH=/srv/rag-admin/admin.db
API_KEYS_PATH=/srv/rag-admin/api_keys.json
TENANTS=edu,web3
DEFAULT_TENANT=edu
RATE_LIMIT_RPM=240
RERANKER_ENABLED=false


À faire : crée et remplis les fichiers ci-dessous avec l’implémentation minimale fonctionnelle + tests (voir § Tests).

1) Modèle de données (SQLite)

Crée tables (SQLAlchemy) :

tenants(id, slug UNIQUE) ; préseed edu, web3.

folders(id, tenant, path TEXT, slug TEXT, parent_id NULLABLE, UNIQUE(tenant, path)).

taxonomy_values(id, tenant, facet, value, UNIQUE(tenant, facet, value)).

Facets edu : doc_type, domain, level, matiere, track

Facets web3 : topic, chain, tool, difficulty

collections(id, tenant, name UNIQUE, folder_id, created_at) ; règle de nommage : f"{tenant}__{slug-or-path-hash}".

api_keys(key TEXT PRIMARY KEY, tenant, scopes TEXT[], origins TEXT[], expires_at NULLABLE)

scopes possibles : folders:read, folders:write, ingest:write, kb:read, jobs:read, keys:issue (opérateur seulement).

jobs(id TEXT PK, tenant, folder_id, collection, source_type, source_value, status{queued|running|done|error}, created_at, updated_at)

job_events(id, job_id, ts, level{info|warn|error}, message) (pour SSE).

Migration : si collection existante ressources_pedagogiques_terminale, la re-mapper vers tenant edu => collection edu__ressources_pedagogiques_terminale sans ré-indexer (alias si supporté, sinon renommage).

2) Sécurité commune

Dans src/common/auth.py :

Charge API_KEYS_PATH (JSON {key: {tenant, cors[], scopes[], note?}}).

Middleware CORS dynamique : si Origin présent, vérifier que la clé permet l’origine ; sinon 403.

Déco require_key(scopes: list[str]) :

Vérifie header X-API-Key, charge l’enregistrement, vérifie tenant (soit ?tenant si fourni, sinon DEFAULT_TENANT) + inclusion scopes.

Injecte dans request.state : tenant, api_key, scopes.

rate_limit(key) : token-bucket par minute (env RATE_LIMIT_RPM), clé = API key.

3) Router Admin (FastAPI, src/admin/router.py)

Endpoints opérateur (protégés par clé avec scope keys:issue et folders:write où pertinent) :

POST /admin/tenants : créer nouveau tenant (rare).

GET /admin/folders?tenant&parent_id : lister.

POST /admin/folders : {tenant, parent_id?, path} → crée hiérarchie + collection si besoin.

GET /admin/taxonomy?tenant : renvoie dictionnaire {facet: [values...]} selon tenant.

POST /admin/taxonomy : {tenant, facet, value} (facets autorisés selon tenant).

POST /admin/api-keys : issue/rotate {tenant, scopes[], origins[], expires_at?} → retourne clé générée.

GET /admin/jobs?tenant&status?&limit? : liste.

GET /admin/jobs/{job_id} : détail + derniers events.

GET /admin/jobs/{job_id}/events : SSE (text/event-stream) → stream des job_events.

Instrumentation : compteurs Prometheus admin_requests_total, admin_failures_total, histogram admin_latency_seconds.

4) Intégration Ingest/Search existantes
/admin/ingest/oneclick (ou recycle /admin/ingest)

Body minimal :

{
  "tenant": "web3",
  "folder_path": "guides/solidity/basics",
  "source_type": "url|gdrive|file|html|markdown",
  "source_value": "https://...",
  "taxonomy": {
    "topic": "solidity",
    "chain": "evm",
    "tool": "foundry",
    "difficulty": "beginner"
  },
  "mode": "text|multimodal",
  "idempotency_key": "optional"
}


Règles :

Auto-créer le folder et la collection si absents.

Attacher métadonnées {tenant, folder_path, ...taxonomy, source_type, origin=api_key_id} à chaque chunk.

Créer job + job_events (feed en temps réel pour SSE).

Respecter rate_limit() et scopes → ingest:write.

/kb/search (read-only externe)

POST, header X-API-Key, ?tenant=web3|edu (fallback DEFAULT_TENANT).

Body { "q": "...", "k": 4, "filters": { ... } }.

Filtre la collection du folder si filters.folder_path présent.

Si RERANKER_ENABLED=true, applique rerank local (e.g. BGE reranker) sur top-K (option).

Scopes requis : kb:read.

CORS par clé appliqué.

Rate-limit appliqué.

Instrumentation : réutiliser vos helpers Prometheus (succès/échec, latence, bytes, chunks).

5) SSE des jobs (remplacer polling)

Dans src/common/sse.py : générateur asynchrone lisant job_events et publiant event: message\ndata: {"level": "...", "msg":"..."}\n\n.
Endpoint GET /admin/jobs/{job_id}/events (protégé jobs:read).
Côté Streamlit : bouton 📡 Suivre en direct (SSE) ouvre un st.components.v1.html avec JS EventSource() pointant sur le backend (proxy Nginx déjà en place).
Met à jour la page Jobs : passer du bouton “Rafraîchir” à SSE + fallback polling.

6) UI Streamlit (rag-ui)

Page Ingestion :

Source (url/file/gdrive/html/markdown),

Tenant selector (edu|web3),

Folder (sélecteur + “Créer un dossier”),

Taxonomie dynamique selon tenant (facets spécifiques),

Lancer l’ingestion → hit /admin/ingest/oneclick avec clé opérateur (stockée côté serveur UI).

Page Dossiers & Taxonomie : CRUD complet via /admin/*.

Page Jobs : liste, détail, SSE.

Page Collections & Recherche : interroge /kb/search (clé lecture).

Cache Streamlit : ttl_cache léger pour listes/facets.

7) Rate-limit & CORS par clé

src/common/ratelimit.py : dict {key -> (tokens, last_refill_ts)}, refill/consommation à chaque requête ; 429 si épuisé.

CORS dynamique : si Origin non listé par api_key.origins → 403 ; en dev, * autorisé pour certaines clés.

8) Tests à livrer (minimaux mais bloquants)

tests/test_kb_search_security.py (déjà fourni précédemment) + ajoute :

clé valide + origin interdit → 403,

dépassement rate-limit → 429,

reranker OFF/ON (flag).

tests/test_admin_crud.py : créer tenant/folder/taxonomie, issuance de clés, 200/401/403 selon scopes.

tests/test_jobs_sse.py : faucher un job, pousser job_events, client SSE reçoit 1+ messages (utiliser starlette TestClient stream).

Tous les tests sans GPU, avec stubs embeddings/Chroma comme précédemment.

9) Observabilité

Expose compteurs :

admin_requests_total{route,method,code,tenant}, admin_failures_total{reason}, admin_latency_seconds,

kb_search_total{tenant}, kb_failures_total{reason}, reranker_seconds,

jobs_events_total{level,tenant}.
Brancher sur /metrics (toggle METRICS_ENABLED OK).

10) Artefacts & Docs

examples/api_keys.sample.json mis à jour avec clés edu_*, web3_*, clés dev locales, scopes/origins.

docs/ :

multi-tenant-admin.md (schémas, flows),

api-external.md (OpenAPI excerpts + curl/Postman),

migration-edu-collections.md (script/commande).

.gitignore : ignorer api_keys.json réel et /srv/rag-admin/*.db.

✅ Critères d’acceptation (merge-gates)

CRUD Admin : création dossier + taxonomie pour edu et web3 via API et UI ; DB SQLite écrite dans /srv/rag-admin/admin.db.

Ingestion 1-clic : crée auto la collection, produit un job, SSE affiche les events en temps réel.

/kb/search : accessible en lecture depuis une origin autorisée, 200 avec clé scope kb:read, 401/403 sinon ; CORS ok.

Rate-limit : 429 si dépassement par clé.

Prometheus : métriques admin/kb/jobs visibles sur /metrics.

Tests : make lint && make typecheck && make test verts (incluant nouveaux tests).

Docs : fichiers d’API et d’exploitation livrés.

Branches & commandes (exécuter)

Implémentation backend + tests

git checkout -B feat/multitenant-admin
# (Copilot : crée les fichiers/routers/services selon ce prompt)
make lint && make typecheck && make test
git add -A
git commit -m "feat(admin): multi-tenant SQLite store, API keys/scopes, CORS per key, rate-limit, SSE jobs; /admin/* and /kb/search wired; tests"
git push -u origin feat/multitenant-admin
gh pr create -t "Admin multi-tenant + accès externes RAG" -b "SQLite sur VPS, clés/scopes/CORS, SSE jobs, endpoints /admin/* et /kb/search, tests & métriques."


UI Streamlit (SSE + formulaires dynamiques)

git checkout -B feat/ui-streamlit-admin
# (Copilot : met à jour les pages Ingestion / Dossiers & Taxonomie / Jobs (SSE) / Collections)
make lint && make typecheck && make test
git add -A
git commit -m "feat(ui): Streamlit admin multi-tenant, ingestion 1-clic, SSE jobs, recherche collections"
git push -u origin feat/ui-streamlit-admin
gh pr create -t "UI admin multi-tenant (SSE)" -b "Formulaires dynamiques edu/web3, création dossiers, SSE jobs, recherche via /kb/search."


Docs + exemples

git checkout -B chore/docs-and-samples
# (Copilot : ajoute docs/* et examples/api_keys.sample.json)
git add -A
git commit -m "docs: multi-tenant admin & external API; sample api_keys; ops notes"
git push -u origin chore/docs-and-samples
gh pr create -t "Docs & samples (multi-tenant)" -b "Guides API externes, migration edu, exemple api_keys."


Important : veille à conserver la rétro-compatibilité du tenant par défaut (DEFAULT_TENANT=edu) pour vos intégrations existantes. En cas de doute, me poser une seule question à la fois et implémenter juste après.
