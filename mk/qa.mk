.PHONY: venv dev-install lint typecheck test smoke all

VENV=.venv
PY=$(VENV)/bin/python
PIP=$(VENV)/bin/pip

# Active un venv local et installe les deps dev + celles des services applicatifs (si présentes)
venv: $(PY)
$(PY):
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	@if [ -f requirements-dev.txt ]; then $(PIP) install -r requirements-dev.txt; fi
	@if [ -f src/ingestor/requirements.txt ]; then $(PIP) install -r src/ingestor/requirements.txt; fi
	@if [ -f src/ui/requirements.txt ]; then $(PIP) install -r src/ui/requirements.txt; fi

dev-install: venv

lint: venv
	$(VENV)/bin/ruff check .

typecheck: venv
# Conseil: commencer permissif, resserrer ensuite par module
	$(VENV)/bin/mypy src

test: venv
	PYTHONPATH=. $(VENV)/bin/pytest -q

smoke:
	@if [ -f infra/scripts/smoke.sh ]; then bash infra/scripts/smoke.sh; else echo "Aucun smoke.sh trouvé"; fi

all: lint typecheck test
