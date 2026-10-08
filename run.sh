#!/usr/bin/env bash
# One command to set up, (re)seed and start the LMS demo.
#   ./run.sh           -> install if needed, seed if no database yet, start on http://localhost:8000
#   ./run.sh --reset   -> wipe and re-seed the demo data, then start
set -euo pipefail
cd "$(dirname "$0")"

PY=${PYTHON:-python3}
if [ ! -x .venv/bin/python ]; then
  echo "Creating virtualenv..."
  "$PY" -m venv .venv
fi
.venv/bin/pip install -q -r requirements.txt

if [ "${1:-}" = "--reset" ] || [ ! -f lms.db ]; then
  .venv/bin/python -m app.seed
fi

echo "LMS running at http://localhost:${PORT:-8000}  (login: head / Shaha@123)"
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
