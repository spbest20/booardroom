#!/usr/bin/env bash
# One command: install if needed, then serve the station on http://localhost:${PORT:-8666}
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; }
[ -f .env ] || { cp .env.example .env; echo "Created .env: add YDC_API_KEY and PARASAIL_API_KEY, then rerun."; exit 1; }
set -a; . ./.env; set +a
exec .venv/bin/uvicorn app.server:app --host 0.0.0.0 --port "${PORT:-8666}"
