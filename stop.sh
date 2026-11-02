#!/usr/bin/env bash
# Stop the servers started by ./start.sh. Also frees the ports if a stray server is listening.
# Usage: ./stop.sh            (both)
#        ./stop.sh backend    (one of: backend | frontend)
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN="$ROOT/.run"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
WHAT="${1:-all}"

stop_one() {  # stop_one <name> <port>
  local name=$1 port=$2 pidfile="$RUN/$1.pid" pid
  if [[ -f "$pidfile" ]]; then
    pid="$(cat "$pidfile")"
    if kill -0 "$pid" 2>/dev/null; then
      # kill the whole process group so uvicorn's reloader / npm's child vite go with it
      pkill -TERM -P "$pid" 2>/dev/null
      kill -TERM "$pid" 2>/dev/null
      for _ in 1 2 3 4 5; do kill -0 "$pid" 2>/dev/null || break; sleep 1; done
      kill -0 "$pid" 2>/dev/null && kill -KILL "$pid" 2>/dev/null
      echo "$name stopped (pid $pid)"
    else
      echo "$name not running (stale pid file removed)"
    fi
    rm -f "$pidfile"
  else
    echo "$name: no pid file"
  fi
  # free the port if anything is still listening (e.g. a server started by hand)
  local stray
  stray="$(lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | tr '\n' ' ')"
  if [[ -n "$stray" ]]; then
    kill -TERM $stray 2>/dev/null; sleep 1
    for p in $stray; do kill -0 "$p" 2>/dev/null && kill -KILL "$p" 2>/dev/null; done
    echo "$name: freed port $port (pids: $stray)"
  fi
}

case "$WHAT" in
  all) stop_one frontend "$FRONTEND_PORT"; stop_one backend "$BACKEND_PORT" ;;
  backend) stop_one backend "$BACKEND_PORT" ;;
  frontend) stop_one frontend "$FRONTEND_PORT" ;;
  *) echo "usage: $0 [all|backend|frontend]" >&2; exit 2 ;;
esac
