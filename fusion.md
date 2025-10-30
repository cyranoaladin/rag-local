Voici un cahier des charges **rigoureux, exploitable**, qui fusionne les avancées de :

* `chore/qa-restore-stubs-and-make` (branche de travail actuelle, outillage/requirements/Makefile remis d’équerre),
* `feat/obs-metrics` (métriques d’obs),
* `feat/copilot-instructions-refresh` (guides Copilot),
* * l’intégration progressive des concepts **RAG-Anything** (multimodal, content_list, VLM « opt-in ») déjà amorcée en Phase 1.

Ci-dessous :

1. un **plan de fusion et d’avancement** très précis (par lots/PRs atomiques),
2. les **diffs / extraits de code** prêts à insérer (FastAPI + Prometheus, schémas multimodaux, tests, CI, Compose, Nginx),
3. un **prompt Copilot R-C-T-C-O** prêt à coller pour qu’il exécute tout **de bout en bout (autorisations incluses)**,
4. une **checklist d’acceptation** objective.

---

# Plan directeur (opinionné) — cible : brancher tout sur `chore/qa-restore-stubs-and-make`

## PR-1 — Observabilité « propre » (merge logique de `feat/obs-metrics` + durcissement)

**Objectif.** Exposer des métriques Prometheus fiables sans gonfler la RAM, couvrir les chemins multimodaux, **désactivables**.

**À faire :**

* Ajouter la dépendance : `prometheus_client>=0.20` dans `src/ingestor/requirements.txt`.
* Instrumenter `src/ingestor/api.py` et `mm_adapter.py` :

  * `Counter`: `ingest_requests_total{route,method}`, `ingest_success_total{modality}`, `ingest_failure_total{reason}`,
    `ingest_chunks_total{modality}`, `ingest_bytes_total`.
  * `Histogram`: `ingest_latency_seconds{route}`, buckets adaptés (p.ex. `[0.1,0.3,0.6,1.0,2.5,5.0]`).
* Endpoint `/metrics` (Starlette `PlainTextResponse`) activé si `METRICS_ENABLED=true`.
* **Timeouts** et **try/except** cohérents : la métrique d’échec doit être alimentée **avant** le rethrow HTTP 4xx/5xx.
* Variables `.env.example` : `METRICS_ENABLED=true|false` (défaut : `true`), `METRICS_NAMESPACE=rag_local`.
* Tests :

  * `tests/test_metrics.py`: spin d’un app test, `GET /metrics` → 200 si activé / 404 si désactivé.
  * Test d’ingest texte (mock Chroma) : vérifier l’incrément des counters `*_success_total` et `ingest_chunks_total{modality="text"}`.
  * Test d’échec (MIME 415) → `ingest_failure_total{reason="unsupported_mime"}`.

**Extraits à insérer (adapter au code actuel)**

```python
# src/ingestor/metrics.py
from prometheus_client import Counter, Histogram, CollectorRegistry, generate_latest
import os

REGISTRY = CollectorRegistry()
NS = os.getenv("METRICS_NAMESPACE", "rag_local")

REQS = Counter(f"{NS}_ingest_requests_total", "Ingest requests", ["route","method"], registry=REGISTRY)
OKS  = Counter(f"{NS}_ingest_success_total",  "Successful ingests", ["modality"], registry=REGISTRY)
FAIL = Counter(f"{NS}_ingest_failure_total",  "Failed ingests", ["reason"], registry=REGISTRY)
CHUNKS = Counter(f"{NS}_ingest_chunks_total", "Chunks pushed", ["modality"], registry=REGISTRY)
BYTES  = Counter(f"{NS}_ingest_bytes_total",  "Total bytes ingested", registry=REGISTRY)
LAT   = Histogram(f"{NS}_ingest_latency_seconds","Ingest latency",{ "route": str }, registry=REGISTRY)
```

```python
# src/ingestor/api.py (extraits)
from .metrics import REQS, OKS, FAIL, CHUNKS, BYTES, LAT, REGISTRY
from prometheus_client import generate_latest
from fastapi.responses import PlainTextResponse

METRICS_ENABLED = os.getenv("METRICS_ENABLED", "true").lower() == "true"

@app.get("/metrics")
def metrics():
    if not METRICS_ENABLED:
        raise HTTPException(status_code=404)
    return PlainTextResponse(generate_latest(REGISTRY), media_type="text/plain; version=0.0.4")
```

**Compose** : ajouter un label ou un port interne scrappable (selon votre stack Prom) ; sinon rien à exposer publiquement.

---

## PR-2 — QA & CI (restore Makefile, stubs, pipeline GitHub Actions)

**Objectif.** Exécuter `ruff`, `mypy`, `pytest` sur PR.

**À faire (Copilot)** :

* `requirements-dev.txt`: `ruff`, `mypy`, `pytest`, `pytest-mock`, `types-requests`, `types-attrs`, `types-beautifulsoup4` (si utilisé), etc.
* `Makefile`: cibles `lint`, `typecheck`, `test`, `smoke` (compose + `infra/scripts/smoke.sh`).
* `.github/workflows/ci.yml` (matrix py3.11/3.12), cache pip, étapes `make lint`, `make typecheck`, `make test`.
  Optionnel : job `smoke` qui `docker compose up -d` (profil `db,llm,api`) puis exécute `infra/scripts/smoke.sh`.

**YAML (Copilot doit créer/adapter)**

```yaml
name: ci
on:
  pull_request:
    paths-ignore: [ "infra/nginx/rendered/**" ]
  push:
    branches: [ main ]
jobs:
  qa:
    runs-on: ubuntu-latest
    strategy:
      matrix: { python: [ "3.11", "3.12" ] }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: ${{ matrix.python }} }
      - run: python -m pip install --upgrade pip
      - run: pip install -r requirements-dev.txt
      - run: make lint
      - run: make typecheck
      - run: make test
```

---

## PR-3 — Multimodal Phase 1.5 (alignement **RAG-Anything**)

**Objectif.** Consolider l’adaptateur multimodal existant avec **trois ajouts sûrs** :

1. **content_list** (injection directe)
2. **métadonnées enrichies** par modalité (caption/hash/dims/table schema)
3. **contrôles d’empreinte mémoire** sur le fallback texte

**À faire (Copilot)** :

* Schéma `schemas.py` : `Chunk(modality: Literal["text","image","table","formula"], text: str|None, blob_ref: str|None, caption:str|None, dims: tuple[int,int]|None, table_csv:str|None, eq_latex:str|None, source:str, sha256:str, page:int|None, …)`
* Nouvel endpoint **POST** `/ingest/content-list?mode=multimodal` acceptant :

  ```json
  {
    "source": "gdrive:/file/123",
    "content_list": [
      {"modality":"text","text":"...","page":3,"source":"..."},
      {"modality":"image","blob_ref":"uploads/img-01.png","caption":"...","dims":[1024,768], "source":"..."}
    ]
  }
  ```

  → prépare les chunks et indexe dans Chroma **sans** re-parser.
* `mm_adapter.py` : si `raganything` dispo : essayer `mineru`/`docling` selon `PARSER=` (env), **timeout** `MM_PARSER_TIMEOUT` déjà câblé, journaliser `coverage: {text:X,img:Y,table:Z,formula:W}`.
* **Fallback texte** : lecture *streamée* (chunks 1 MiB) et découpe `MM_MAX_CHARS_PER_CHUNK` pour éviter les pics RAM.

**Tests** :

* `tests/test_content_list.py` : post d’une `content_list` mixte → vérifie `ingest_chunks_total{image|text}` et présence métadonnées dans Chroma (mock).

---

## PR-4 — Nginx + envsubst, upstreams, sécurité

**Objectif.** Finaliser les vhosts paramétriques et la mise en frontal « web » unique.

**À faire** :

* Confirmer les templates Nginx `rag-ui.conf.template` / `rag-n8n.conf.template` : `proxy_pass http://${NGINX_UI_UPSTREAM}` etc., `client_max_body_size $NGINX_CLIENT_MAX_BODY_SIZE`, HSTS/PFS optionnels.
* Script `make nginx-render` : `envsubst < infra/nginx/rag-ui.conf.template > infra/nginx/rendered/rag-ui.conf` etc.
* **README-PROD.md** : flux complet « render → `nginx -t` → reload ».

---

## PR-5 — UX console (Streamlit) + garde-fous

**Objectif.** Petites finitions utiles :

* UI: badge modalité (déjà), pagination, `top_k` borné, **sanitization** stricte et masquage tokens/URLs.
* **BasicAuth** au niveau Nginx pour l’UI (si exposée).

---

## PR-6 — Observabilité étendue (optionnel mais recommandé)

**Objectif.** **Structured logging** JSON (clés : `ts, lvl, msg, route, latency_ms, bytes, modality, source, ip`)

* Paramètre `.env`: `LOG_FORMAT=json|text`.
* Exemple Fluent-Bit/filebeat dans `infra/observability/` (facultatif), doc d’intégration.

---

# Snippets prêts à l’emploi (insérer/adapter)

## 1) Tests métriques — `tests/test_metrics.py`

```python
import os
from fastapi.testclient import TestClient
from ingestor.api import app

def test_metrics_enabled():
    os.environ["METRICS_ENABLED"] = "true"
    c = TestClient(app)
    r = c.get("/metrics")
    assert r.status_code == 200
    assert b"rag_local_ingest_requests_total" in r.content

def test_metrics_disabled():
    os.environ["METRICS_ENABLED"] = "false"
    c = TestClient(app)
    r = c.get("/metrics")
    assert r.status_code == 404
```

## 2) Endpoint content_list — `src/ingestor/api.py` (extrait)

```python
class ContentItem(BaseModel):
    modality: Literal["text","image","table","formula"]
    text: str | None = None
    blob_ref: str | None = None
    caption: str | None = None
    dims: tuple[int,int] | None = None
    table_csv: str | None = None
    eq_latex: str | None = None
    page: int | None = None
    source: str

class ContentListIngest(BaseModel):
    source: str
    content_list: list[ContentItem]

@app.post("/ingest/content-list")
def ingest_content_list(payload: ContentListIngest, mode: str = "multimodal"):
    _enforce_security(...)
    with LAT.labels(route="/ingest/content-list").time():
        REQS.labels(route="/ingest/content-list", method="POST").inc()
        chunks = _prepare_chunks_from_content_list(payload)
        total_bytes = sum(len(c.text or b"") for c in chunks if c.modality=="text")
        BYTES.inc(total_bytes)
        # push to chroma ...
        for c in chunks:
            CHUNKS.labels(modality=c.modality).inc()
            OKS.labels(modality=c.modality).inc()
    return {"status":"ok","added":len(chunks)}
```

## 3) Makefile (extrait)

```make
.PHONY: lint typecheck test smoke
lint:
	ruff check .
typecheck:
	mypy src
test:
	python -m pytest -q
smoke:
	bash infra/scripts/smoke.sh
```

## 4) requirements-dev.txt (extrait)

```
ruff==0.6.4
mypy==1.11.2
pytest==8.3.3
pytest-mock>=3.14
types-requests
types-attrs
```

## 5) CI — `.github/workflows/ci.yml`

*(voir bloc YAML plus haut)*

---

# Checklist d’acceptation (à coller dans chaque PR)

* [ ] `make lint` propre
* [ ] `make typecheck` propre
* [ ] `make test` ≥ 8 tests → **OK** (incluant `test_metrics.py` / `test_content_list.py`)
* [ ] `docker compose --profile db,llm,api up -d` → `infra-ingestor-1` **healthy**
* [ ] `bash infra/scripts/smoke.sh` → `/health OK` & `/ingest` → `{"status":"ok"...}`
* [ ] `/metrics` 200 avec `METRICS_ENABLED=true`, 404 sinon
* [ ] Multimodal activé : `--profile multimodal` + `smoke.sh` (PNG/PDF) → `modality badges` visibles en UI
* [ ] README/README-PROD mis à jour (envsubst, profils, routes)

---

## Deux remarques stratégiques (opinion)

1. **L’opt-in multimodal** par profil+env est le bon choix pour un VPS : vous gardez la stabilité du chemin texte et n’activez l’OCR/LibreOffice qu’en cas d’usage.
2. **Métriques et logs JSON** : ce sont vos meilleurs « airbags ». Avant d’ajouter du VLM, verrouillez l’observabilité et les tests ; c’est ce qui rendra les futures régressions triviales à diagnostiquer.

