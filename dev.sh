#!/usr/bin/env bash
# Starts engine (8000) + API server (4000) + React client (5173). Ctrl+C stops all three.
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
[ -f "$ROOT/.env" ] && { set -a; . "$ROOT/.env"; set +a; }
export DATA_DIR="${DATA_DIR:-$ROOT/data}"
mkdir -p "$DATA_DIR"

if [ ! -d "$ROOT/analysis/.venv" ]; then echo "Missing analysis/.venv - see README step 2"; exit 1; fi
if [ ! -d "$ROOT/server/node_modules" ] || [ ! -d "$ROOT/client/node_modules" ]; then echo "Run 'npm install' in server/ and client/ first - see README step 3"; exit 1; fi

trap 'kill 0' EXIT INT TERM
( cd "$ROOT/analysis" && exec .venv/bin/python3 -m uvicorn main:app --port 8000 ) &
( cd "$ROOT/server" && exec npm run dev ) &
( cd "$ROOT/client" && exec npm run dev ) &
echo ""; echo "  App:     http://localhost:5173"; echo "  API:     http://localhost:4000/api/health"; echo "  Engine:  http://localhost:8000/docs"; echo ""
wait
