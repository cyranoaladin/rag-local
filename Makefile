# Makefile venv-aware pour lint/type/tests/obs

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

.PHONY: help venv install-dev lint typecheck test smoke \
	obs-up obs-down obs-smoke obs-quickcheck obs-restart obs-status print-tools

help:
	@echo "Targets : venv | install-dev | lint | typecheck | test | smoke | obs-up | obs-smoke | obs-down | obs-restart | obs-status | print-tools"

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
	$(PYTEST) -q

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
	else echo "No infra/scripts/obs_smoke.sh"; fi

obs-quickcheck:
	@if [ -x infra/scripts/metrics_quickcheck.sh ]; then \
		PROM_URL=$${PROM_URL:-http://127.0.0.1:19090} \
		TARGET_URL=$${TARGET_URL:-http://127.0.0.1:18001/metrics} \
		bash infra/scripts/metrics_quickcheck.sh; \
	else \
		echo "infra/scripts/metrics_quickcheck.sh manquant (non bloquant)"; \
	fi

print-tools:
	@echo "PY         = $(PY)"
	@$(PY) -c "import shutil; print('RUFF path  = ' + (shutil.which('ruff') or '(module)'))"
	@$(PY) -c "import shutil; print('MYPY path  = ' + (shutil.which('mypy') or '(module)'))"
	@$(PY) -c "import shutil; print('PYTEST path= ' + (shutil.which('pytest') or '(module)'))"
