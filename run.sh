#!/usr/bin/env bash
# JARVIS - one command to start backend + Electron UI (development)
set -e
cd "$(dirname "$0")"

VENV_PY="venv/bin/python"
BACKEND_PORT=8765
BACKEND_PID=""

cleanup() {
  if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null
    echo ""
    echo "[JARVIS] Backend stopped."
  fi
}
trap cleanup EXIT INT TERM

if ! curl -s -m 2 "http://127.0.0.1:${BACKEND_PORT}/api/status" > /dev/null 2>&1; then
  echo "[JARVIS] Starting backend..."
  "$VENV_PY" -u src/server.py > /tmp/jarvis_backend.log 2>&1 &
  BACKEND_PID=$!
  for i in $(seq 1 120); do
    if curl -s -m 1 "http://127.0.0.1:${BACKEND_PORT}/api/status" > /dev/null 2>&1; then
      break
    fi
    sleep 0.5
  done
  if ! curl -s -m 1 "http://127.0.0.1:${BACKEND_PORT}/api/status" > /dev/null 2>&1; then
    echo "[JARVIS] Backend failed to start. Log: /tmp/jarvis_backend.log"
    exit 1
  fi
  echo "[JARVIS] Backend online."
else
  echo "[JARVIS] Backend already running."
fi

cd electron
exec npx electron . --no-sandbox
