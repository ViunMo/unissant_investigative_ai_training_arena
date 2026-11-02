#!/usr/bin/env bash
# Start the Investigative AI Training Arena: FastAPI backend on :8000 and Vite frontend on :5173.
# Usage: ./start.sh            (both)
#        ./start.sh backend    (one of: backend | frontend)
# Logs and PID files live in .run/. Stop with ./stop.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN="$ROOT/.run"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
WHAT="${1:-all}"
mkdir -p "$RUN"

port_in_use() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

pid_alive() { [[ -f "$1" ]] && kill -0 "$(cat "$1")" 2>/dev/null; }

wait_for() {  # wait_for <url> <seconds>
  local url=$1 secs=$2 i=0
  until curl -fsS "$url" >/dev/null 2>&1; do
    sleep 1; i=$((i + 1))
    if (( i >= secs )); then return 1; fi
  done
}

start_backend() {
  if pid_alive "$RUN/backend.pid"; then
    echo "backend already running (pid $(cat "$RUN/backend.pid"))"; return
  fi
  if port_in_use "$BACKEND_PORT"; then
    echo "port $BACKEND_PORT is already in use by another process; run ./stop.sh first" >&2; exit 1
  fi
  cd "$ROOT/backend"
  if [[ ! -x .venv/bin/python ]]; then
    echo "creating backend venv..."
    uv venv --python 3.12 .venv >/dev/null
    (source .venv/bin/activate && uv pip install -q -r requirements.txt)
  fi
  [[ -f .env ]] || { echo "backend/.env not found; copying .env.example (mock runtime until you add credentials)"; cp .env.example .env; }
  nohup .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT" \
    >"$RUN/backend.log" 2>&1 &
  echo $! >"$RUN/backend.pid"
  if wait_for "http://127.0.0.1:$BACKEND_PORT/api/health" 30; then
    echo "backend  up  http://localhost:$BACKEND_PORT  (docs: /docs, log: .run/backend.log)"
    curl -fsS "http://127.0.0.1:$BACKEND_PORT/api/health"; echo
  else
    echo "backend failed to start; see .run/backend.log" >&2; tail -20 "$RUN/backend.log" >&2; exit 1
  fi
}

start_frontend() {
  if pid_alive "$RUN/frontend.pid"; then
    echo "frontend already running (pid $(cat "$RUN/frontend.pid"))"; return
  fi
  if port_in_use "$FRONTEND_PORT"; then
    echo "port $FRONTEND_PORT is already in use by another process; run ./stop.sh first" >&2; exit 1
  fi
  cd "$ROOT/frontend"
  [[ -d node_modules ]] || { echo "installing frontend dependencies..."; npm install --silent; }
  nohup npm run dev -- --port "$FRONTEND_PORT" --strictPort >"$RUN/frontend.log" 2>&1 &
  echo $! >"$RUN/frontend.pid"
  if wait_for "http://127.0.0.1:$FRONTEND_PORT/" 30; then
    echo "frontend up  http://localhost:$FRONTEND_PORT  (log: .run/frontend.log)"
  else
    echo "frontend failed to start; see .run/frontend.log" >&2; tail -20 "$RUN/frontend.log" >&2; exit 1
  fi
}

case "$WHAT" in
  all) start_backend; start_frontend ;;
  backend) start_backend ;;
  frontend) start_frontend ;;
  *) echo "usage: $0 [all|backend|frontend]" >&2; exit 2 ;;
esac
