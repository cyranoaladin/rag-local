VENV_PY := $(CURDIR)/.venv/bin/python
PYTHON ?= $(if $(wildcard $(VENV_PY)),$(VENV_PY),python3)
SRC_DIRS := src tests

.PHONY: lint typecheck test

lint:
	$(PYTHON) -m ruff check $(SRC_DIRS)

typecheck:
	$(PYTHON) -m mypy src

test:
	$(PYTHON) -m pytest
