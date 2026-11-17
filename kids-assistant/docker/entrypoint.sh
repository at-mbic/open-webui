#!/usr/bin/env bash
# Start Open WebUI, then apply the kids' setup and safety audit.
# Fails closed: if setup or the audit fails, the server is stopped so the
# kids never get an instance that isn't locked down.
set -u

cd /app/backend
bash start.sh &
SERVER_PID=$!

stop() { kill -TERM "$SERVER_PID" 2>/dev/null; wait "$SERVER_PID"; exit "${1:-0}"; }
trap 'stop 0' TERM INT

echo "[study-buddy] waiting for Open WebUI to start..."
for _ in $(seq 1 300); do
  if curl -fs "http://127.0.0.1:${PORT:-8080}/health" >/dev/null 2>&1; then break; fi
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then echo "[study-buddy] Open WebUI exited during startup"; exit 1; fi
  sleep 1
done

if ! python3 /app/kids-assistant/docker/firstboot.py; then
  echo "[study-buddy] SETUP OR SAFETY AUDIT FAILED - stopping so the kids can't use an unsafe instance."
  echo "[study-buddy] See the messages above. Fix the cause, then restart the container."
  stop 1
fi

echo "[study-buddy] ready: open http://localhost:3000"
wait "$SERVER_PID"
