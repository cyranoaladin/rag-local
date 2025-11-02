# 🧩Audit & Durcissement RAG local (VPS) — R-C-T-C-O

**Rôle (R) — Persona**
Agis comme **Architecte Python/MLOps Senior** spécialisé en **RAG CPU-only sur VPS à ressources contraintes**, optimisation I/O, sécurité d’API, et durcissement Nginx/TLS. Tu dois raisonner **au-delà d’un fichier** (vision système).

**Contexte (C)**
Codebase actuelle (répertoires clés) :

* `infra/` : `docker-compose.yml`, `docker-compose.override.yml` ou `docker-compose.dev.yml`, `.env.example`, `nginx/{rag-ui.conf.template, rag-n8n.conf.template, README.md}`, `scripts/smoke.sh`, `ollama/ollama-tags.json`.
* `src/ingestor/` : `api.py`, `requirements.txt`, `Dockerfile`.
* `src/ui/` : `app.py`, `requirements.txt`, `Dockerfile`.
* `tests/`, `requirements-dev.txt`, `pyproject.toml`, `.cspell.json`, `README.md`, `README-PROD.md`, `SPEC.md`.
  Architecture cible : **Ollama (CPU) + ChromaDB + Ingestor (FastAPI) + UI (Streamlit) + (optionnel) n8n**. Exposition publique **uniquement via Nginx+TLS**. Pas d’API externes.

---

## 🎯 Tâches (T) — en étapes séquencées et livrables concrets

### 0) Préambule (branche & règles)

1. Crée une branche : `chore/audit-vps-rag`.
2. Toutes tes modifs doivent :

   * respecter **CPU-only**, **pas de nouvelles dépendances lourdes**, pas d’augmentation RAM notable.
   * conserver le **reverse-proxy Nginx + envsubst**.
   * inclure **tests** (unit, smoke) et **docs**.

### 1) Carte mentale & flux (document court)

* Produit un **résumé d’architecture** (data flow : Ingestion ➜ Embeddings ➜ Indexation ➜ Recherche ➜ Contexte ➜ Génération) en 10–15 lignes + schéma ASCII si utile.
* Indique pour chaque étape : fichiers impliqués, principaux paramètres, et risques de latence/mémoire.

### 2) Audit & correctifs — **Ingestor (FastAPI)** `src/ingestor/api.py`

* **Sécurité** :

  * Applique/valide **X-API-Token** obligatoire et **IP allowlist** (déjà présents ? consolide).
  * Timeouts réseau explicites (`requests`), `User-Agent` dédié, vérifs anti-redirect ouvert.
  * Journalisation structurée **sans verbosité excessive**.
* **Robustesse** :

  * Gère **OLLAMA_URL** et **CHROMA_HOST:PORT** par env, retries raisonnables.
  * Évite copies inutiles (streams/chunks), supprime buffers temporaires inutiles.
  * Ajoute **timeouts** pour Ollama/Chroma (embedding/index) et erreurs claires.
* **Perf budget** (cibles locales) :

  * RAM ingestor **≤ 250 MiB** lors d’un `POST /ingest` 100 Ko.
  * Latence `/health` **≤ 100 ms**, ingestion URL 100 Ko **≤ 2 s** si Ollama déjà chaud.
* Ajoute/complète des **tests** dans `tests/` :

  * token manquant → 401 ; IP refusée → 403 ; acceptée → 200.
  * ingestion URL factice → `{"status":"ok","added":…}` (mocker réseau).

### 3) Audit & correctifs — **UI (Streamlit)** `src/ui/app.py`

* Supprime toute option non supportée côté API (ex. `py_dir` si l’API ne gère pas).
* Ajoute **timeouts**, messages d’erreurs UX clairs, évite recomputations (mise en cache sobre).
* Garantis que l’UI **ne publie aucun secret** dans les logs.
* L’UI **ne doit pas** être exposée sans Nginx ; en dev : ports bouclés `127.0.0.1`.

### 4) Audit & correctifs — **Nginx** `infra/nginx/*.template`

* Confirme que les templates n’utilisent **pas** `${VAR:-def}` (envsubst only).
* Garde **client_max_body_size** via `NGINX_CLIENT_MAX_BODY_SIZE` (ex. `16m`).
* Headers sécurité : `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options`, `Permissions-Policy`, **CSP stricte minimale** (garde la compat) ; **HSTS** en prod (doc).
* Exemple `envsubst` reproductible dans `infra/nginx/README.md` (sans shell-defaults).

### 5) Audit & correctifs — **Compose & DEV ergonomique** `infra/docker-compose*.yml`

* Confirme profils (`db,llm,api,ui`), **ports non publiés** en prod.
* Fichier dev : publication **localhost** (`127.0.0.1:18001->8001`, `127.0.0.1:18501->8501`), `XDG_CACHE_HOME=/tmp`, `tmpfs: /tmp`.
* **Healthchecks** Python ou HTTP, `depends_on` corrects.
* Logging json-file avec `max-size`.
* Gardes : pas d’addition de services lourds.

### 6) **Chunking/Retrieval** (qualité & latence VPS)

* Analyse la **taille de chunk** / **overlap** utilisés dans l’ingestion.
* Propose une **taille & overlap** alternatives **argumentées** (objectif : réduire latence et taille contexte **sans** casser le rappel).
* Limite `k` par défaut (ex. `k=3..5`) et documente comment l’ajuster.

### 7) **Tests & Outils**

* Complète `requirements-dev.txt` (ruff, mypy, pylint, pytest, httpx/pytest-mock si besoin).
* Ajoute/ajuste :

  * `pyproject.toml` (ruff/pylint/mypy cibles raisonnables),
  * `Makefile` : `lint`, `typecheck`, `test`, `smoke`, `compose-up`, `compose-down`,
  * `.cspell.json` (termes projet),
  * `infra/scripts/smoke.sh` (idempotent), si manquant.
* **À exécuter** localement :

  * `python -m ruff check .`
  * `python -m mypy src`
  * `python -m pylint src || true`
  * `python -m pytest -q`
  * `bash infra/scripts/smoke.sh`
* **Colle les sorties** (résumé) dans la PR.

### 8) **Docs**

* `README.md` : section **“Démarrer en local (dev)”** avec compose dev + smoke.
* `README-PROD.md` : procédure **envsubst** + **Nginx** + **Certbot** ; rappel que les services écoutent en loopback et que seule la **terminaison TLS** est publique.
* `SPEC.md` : ajoute endpoints `/health`, limites connues (chunking, k).

### 9) **.github/copilot-instructions.md** (contraintes globales VPS)

Ajoute/ajuste avec ces règles persistantes :

* **Pas de nouvelles dépendances lourdes** sans justification.
* Prioriser **O(n log n)** vs **O(n²)** ; éviter copies mémoire.
* Favoriser **streaming de fichiers** et **générateurs**.
* Timeouts réseau par défaut (≤ 10 s), retries bornés.
* Ne jamais exposer de secrets dans logs ou réponses.
* En prod : ports non publiés ; exposition via Nginx+TLS uniquement.

---

## ⛳️ Contraintes (C) — garde-fous non négociables

* **VPS CPU-only**, RAM limitée. Budgets cibles :

  * Ingestor **≤ 250 MiB** (peak) lors d’une ingestion 100 Ko.
  * UI **≤ 200 MiB** au repos.
* **Aucune nouvelle lib lourde** (ex. GPU, OCR non nécessaire).
* **Compatibilité** : Python 3.11, Linux AMD64.
* **Sécurité** : token obligatoire, allowlist optionnelle, pas de CORS permissif public, n8n non exposé sans basic-auth.
* **Reproductible** : tout doit passer par env `.env` + `envsubst` + compose.
* **Pas de breaking change** d’API sans doc/migration.

---

## 📦 Sorties attendues (O)

1. **PR unique** sur `chore/audit-vps-rag` contenant :

   * Les **diffs** de code/doc outillés ci-dessus.
   * Un **résumé d’architecture** (10–15 lignes).
   * Une **section “Bench minimal”** : latence `/health`, `/ingest` (100 Ko), empreinte RAM approximative (avant/après si dispo).
   * Les **sorties** de `ruff/mypy/pylint/pytest` et du **smoke** (codes HTTP, JSON).
2. **Aucun secret** committé.
3. Commits **clairs** : `feat(ingestor)`, `chore(nginx)`, `docs(prod)`, etc.

---

## 🧪 Garde-fous de validation (à exécuter et coller en PR)

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m mypy src
python -m pylint src || true
bash infra/scripts/smoke.sh
grep -R '\${[^}]*:-' infra/nginx -n || echo "OK: no shell-defaults in templates"
docker compose -f infra/docker-compose.yml config >/dev/null && echo "compose: OK"
```

> Si un point bloque (typage strict, healthcheck, etc.), **propose une alternative** compatible VPS et explique le compromis (latence vs rappel, RAM vs chunking).

---

**Objectif final :** une PR **mergeable** qui durcit sécurité/perf/stabilité, **sans alourdir** la stack, avec tests + doc + scripts prêts pour déploiement VPS (Nginx+TLS).
