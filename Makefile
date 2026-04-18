SHELL := /bin/bash
VENVDIR ?= .venv

# Detecte un Python de venv si disponible, sinon retombe sur python3
PY_SYS := $(shell command -v python3 2>/dev/null || echo python3)
PY_VENV := $(VENVDIR)/bin/python
ifeq ($(wildcard $(PY_VENV)),)
  PY := $(PY_SYS)
else
  PY := $(PY_VENV)
endif

RUFF   := $(PY) -m ruff
MYPY   := $(PY) -m mypy
PYTEST := $(PY) -m pytest

.PHONY: help venv install-dev lint typecheck test test-integration smoke \
    obs-up obs-down obs-smoke obs-quickcheck obs-restart obs-status \
    compose-test-up compose-test-down print-tools dev compose-up compose-down compose-restart

help:
	@echo "Targets : venv | install-dev | lint | typecheck | test | test-integration | smoke | obs-up | obs-smoke | obs-down | obs-restart | obs-status | compose-test-up | compose-test-down | print-tools | dev | compose-up | compose-down | compose-restart"

# Cree le venv si absent et met pip a jour

venv:
	@if [ ! -x "$(PY_VENV)" ]; then \
		echo "-> create venv in $(VENVDIR)"; \
		$(PY_SYS) -m venv "$(VENVDIR)"; \
		"$(PY_VENV)" -m pip install -U pip; \
	fi

# Installe dependances runtime + dev si dispo
install-dev: venv
	@if [ -f requirements.txt ]; then "$(PY)" -m pip install -r requirements.txt; fi
	@if [ -f requirements-dev.txt ]; then "$(PY)" -m pip install -r requirements-dev.txt; fi
	# Fallback minimal si requirements-dev.txt est absent/incomplet
	@for mod in ruff mypy pytest; do \
		$(PY) -c "import importlib; importlib.import_module('$$mod')" >/dev/null 2>&1 || $(PY) -m pip install $$mod; \
	done

lint: install-dev
	$(RUFF) check .

typecheck: install-dev
	$(MYPY) src

test: install-dev
	PYTHONPATH=src $(PYTEST) -q -m "not integration"

test-integration: install-dev
	$(PYTEST) tests/integration -q

# Smoke RAG deja present (si votre repo inclut infra/scripts/smoke.sh)
smoke:
	@if [ -x infra/scripts/smoke.sh ]; then bash infra/scripts/smoke.sh; else echo "No infra/scripts/smoke.sh"; fi

# Observabilite (nomenclature compatible avec vos derniers commits)
# Utilise les profils Compose db,llm,api,obs + env file s'il existe
obs-up:
	@ENV_FILE="infra/.env"; [ -f infra/.env.ci ] && ENV_FILE="infra/.env.ci"; \
	echo "-> env: $$ENV_FILE"; \
	COMPOSE_PROFILES=db,llm,api,obs docker compose \
	  -f infra/docker-compose.yml \
	  -f infra/docker-compose.obs.yml \
	  -f infra/docker-compose.obs.override.yml \
	  --env-file "$$ENV_FILE" \
	  up -d --remove-orphans

obs-down:
	@ENV_FILE="infra/.env"; [ -f infra/.env.ci ] && ENV_FILE="infra/.env.ci"; \
	COMPOSE_PROFILES=db,llm,api,obs docker compose \
	  -f infra/docker-compose.yml \
	  -f infra/docker-compose.obs.yml \
	  -f infra/docker-compose.obs.override.yml \
	  --env-file "$$ENV_FILE" \
	  down --remove-orphans

obs-restart: obs-down obs-up


obs-status:
	@docker compose -f infra/docker-compose.yml ps || true

obs-smoke:
	@if [ -x infra/scripts/obs_smoke.sh ]; then bash infra/scripts/obs_smoke.sh; \
		else \
			echo "No infra/scripts/obs_smoke.sh"; \
		fi

obs-quickcheck:
	@if [ -x infra/scripts/metrics_quickcheck.sh ]; then \
		PROM_URL=$${PROM_URL:-http://127.0.0.1:19090} \
		TARGET_URL=$${TARGET_URL:-http://127.0.0.1:18001/metrics} \
		bash infra/scripts/metrics_quickcheck.sh; \
	else \
		echo "infra/scripts/metrics_quickcheck.sh manquant (non bloquant)"; \
	fi

compose-test-up:
	@docker compose -f infra/docker-compose.test.yml up -d --remove-orphans

dev:

compose-test-down:
	@docker compose -f infra/docker-compose.test.yml down --remove-orphans

print-tools:
	@echo "PY         = $(PY)"
	@$(PY) -c "import shutil; print('RUFF path  = ' + (shutil.which('ruff') or '(module)'))"
	@$(PY) -c "import shutil; print('MYPY path  = ' + (shutil.which('mypy') or '(module)'))"
	@$(PY) -c "import shutil; print('PYTEST path= ' + (shutil.which('pytest') or '(module)'))"

dev:
	python -V && pip -V

compose-up:
	docker compose -f infra/docker-compose.yml --env-file infra/.env up -d

compose-down:
	docker compose -f infra/docker-compose.yml --env-file infra/.env down --remove-orphans

compose-restart: compose-down compose-up

# ═══════════════════════════════════════════════
# RAG SERVICE v2 — TARGETS
# ═══════════════════════════════════════════════

COMPOSE_V2=docker compose -f infra/docker-compose.v2.yml --env-file infra/.env

.PHONY: v2-up v2-down v2-build v2-migrate-chroma v2-migrate-qdrant v2-pull-models \
        v2-eval v2-test v2-security-check v2-logs v2-stats v2-cleanup

## v2: Démarrage complet
v2-up:
	$(COMPOSE_V2) up -d --build
	@echo "⏳ Attente services..."
	@sleep 10
	@$(COMPOSE_V2) exec ingestor curl -sf http://localhost:8001/health || echo "⚠️  Ingestor not ready yet"
	@echo "✅ RAG Service v2 démarré"

## v2: Arrêt
v2-down:
	$(COMPOSE_V2) down

## v2: Build images
v2-build:
	$(COMPOSE_V2) build --parallel

## v2: Migration ChromaDB → pgvector
v2-migrate-chroma:
	$(COMPOSE_V2) exec ingestor python /app/scripts/migrate_chroma_to_pgvector.py \
		--chroma-host chroma --chroma-port 8000 \
		--pg-dsn "$$DATABASE_URL_SYNC" \
		--tenant nsi

## v2: Migration Qdrant → pgvector
v2-migrate-qdrant:
	$(COMPOSE_V2) exec ingestor python /app/scripts/migrate_qdrant_to_pgvector.py \
		--qdrant-url http://localhost:6333 \
		--collection programmes_vf \
		--pg-dsn "$$DATABASE_URL_SYNC" \
		--tenant nexus

## v2: Pull modèles Ollama nécessaires
v2-pull-models:
	$(COMPOSE_V2) exec ollama ollama pull nomic-embed-text:v1.5
	$(COMPOSE_V2) exec ollama ollama pull mistral:7b-instruct || true

## v2: Évaluation qualité RAG
v2-eval:
	@echo "📊 Lancement de l'évaluation RAG..."
	@curl -sf -H "Authorization: Bearer $${API_SECRET_KEY}" http://localhost:8001/eval/nsi | python3 -m json.tool || echo "⚠️  Eval nsi failed"
	@curl -sf -H "Authorization: Bearer $${API_SECRET_KEY}" http://localhost:8001/eval/nexus | python3 -m json.tool || echo "⚠️  Eval nexus failed"

## v2: Tests
v2-test:
	$(PYTEST) tests/test_hybrid_search.py -v
	@echo "ℹ️  Integration tests require DATABASE_URL_TEST to be set"

## v2: Vérification sécurité (ports, secrets)
v2-security-check:
	@echo "🔒 Vérification des ports exposés..."
	@ss -tlnp 2>/dev/null | grep -E '5433|5434|5544|8000|9005|9006' && \
		echo "⚠️  ATTENTION : ports exposés sur 0.0.0.0" || \
		echo "✅ Aucun port sensible exposé"
	@echo ""
	@echo "🔑 Vérification des secrets..."
	@grep -r "CHANGE_ME\|ci_token\|ci_mdp\|password123" infra/.env 2>/dev/null && \
		echo "🔴 SECRETS PAR DÉFAUT DÉTECTÉS — Modifier immédiatement" || \
		echo "✅ Pas de secrets par défaut détectés"

## v2: Logs
v2-logs:
	$(COMPOSE_V2) logs -f ingestor worker

## v2: Stats en direct
v2-stats:
	@curl -sf -H "Authorization: Bearer $${API_SECRET_KEY}" http://localhost:8001/stats/nsi | python3 -m json.tool || echo "⚠️  Stats nsi unavailable"
	@curl -sf -H "Authorization: Bearer $${API_SECRET_KEY}" http://localhost:8001/stats/nexus | python3 -m json.tool || echo "⚠️  Stats nexus unavailable"

## v2: Nettoyage des instances orphelines
v2-cleanup:
	@echo "🧹 Nettoyage des instances RAG orphelines..."
	@echo "  Instances à vérifier manuellement :"
	@echo "  - /home/alaeddine/nexus_rag_pipeline/chroma_db/"
	@echo "  - /home/alaeddine/workspace-agents/ (scaffold vide)"
	@echo "  - /srv/rag/ingestor/api.py (snapshot orphelin)"
