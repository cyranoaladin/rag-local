#!/usr/bin/env bash
set -Eeuo pipefail
VENVDIR="${VENVDIR:-.venv}"
PY_SYS="$(command -v python3 || echo python3)"
if [ ! -x "${VENVDIR}/bin/python" ]; then
  echo "-> creating venv in ${VENVDIR}"
  "${PY_SYS}" -m venv "${VENVDIR}"
  "${VENVDIR}/bin/python" -m pip install -U pip
fi
if [ -f requirements.txt ]; then "${VENVDIR}/bin/python" -m pip install -r requirements.txt; fi
if [ -f requirements-dev.txt ]; then "${VENVDIR}/bin/python" -m pip install -r requirements-dev.txt; fi
"${VENVDIR}/bin/python" - << "PY"
import importlib, subprocess, sys
for mod in ("ruff", "mypy", "pytest"):
    try:
        importlib.import_module(mod)
    except Exception:
        subprocess.check_call([sys.executable, "-m", "pip", "install", mod])
print("-> tool versions")
import subprocess
for mod in ("ruff", "mypy", "pytest"):
    try:
        output = subprocess.check_output([sys.executable, "-m", mod, "--version"], text=True, stderr=subprocess.STDOUT)
        print(mod, output.strip())
    except Exception:
        print(mod, "ok")
PY
