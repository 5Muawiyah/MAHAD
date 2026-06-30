#!/usr/bin/env bash
# MAHAD launcher (macOS / Linux). On first run it creates .venv and installs
# the requirements (one-time, a few minutes), then starts MAHAD. The book is a
# simulated USD portfolio; no real orders are placed.
#
# MAHAD supports Python 3.11 to 3.13 (3.13 recommended). The launcher picks a
# supported interpreter; override with PYTHON=/path/to/python3.13 if needed.
set -e
cd "$(dirname "$0")"

_supported() {   # exit 0 if $1 is a Python in [3.11, 3.13]
  "$1" -c 'import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] <= (3,13) else 1)' >/dev/null 2>&1
}

if [ -x ".venv/bin/python" ]; then
  if ! _supported ".venv/bin/python"; then
    echo "[MAHAD] ERROR: the existing .venv uses an unsupported Python version." >&2
    echo "[MAHAD] Delete the .venv folder and run this script again to recreate it" >&2
    echo "[MAHAD] with Python 3.13." >&2
    exit 1
  fi
else
  PY=""
  if [ -n "${PYTHON:-}" ] && _supported "${PYTHON}"; then
    PY="${PYTHON}"
  else
    for c in python3.13 python3.12 python3.11 python3 python; do
      if command -v "$c" >/dev/null 2>&1 && _supported "$c"; then PY="$c"; break; fi
    done
  fi
  if [ -z "$PY" ]; then
    echo "[MAHAD] ERROR: no supported Python was found." >&2
    echo "[MAHAD] MAHAD needs Python 3.13 (the supported range is 3.11 to 3.13)." >&2
    echo "[MAHAD] Install 3.13 from https://www.python.org/downloads/ (or set PYTHON=...), then re-run." >&2
    exit 1
  fi
  echo "[MAHAD] First run: creating .venv with ${PY} and installing requirements (one-time) ..."
  "$PY" -m venv .venv
  ./.venv/bin/python -m pip install --upgrade pip
  ./.venv/bin/python -m pip install -r requirements.txt
fi
echo "[MAHAD] Starting MAHAD - simulated portfolio ..."
exec ./.venv/bin/python -m mahad
