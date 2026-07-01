#!/usr/bin/env bash
# Temporary public URL via Cloudflare Quick Tunnel (no account login required).
# Exposes the local pipeline status server at a random *.trycloudflare.com URL.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PORT="${STATUS_PORT:-8765}"
PID_FILE="$ROOT/deploy/cloudflare/.status-server.pid"
LOG_DIR="$ROOT/deploy/cloudflare/logs"
mkdir -p "$LOG_DIR"

cleanup() {
  echo "==> Stopping status server and tunnel..."
  [[ -f "$PID_FILE" ]] && kill "$(cat "$PID_FILE")" 2>/dev/null || true
  rm -f "$PID_FILE"
  pkill -f "cloudflared tunnel --url http://localhost:${PORT}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Status server
if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "==> Status server already running (pid $(cat "$PID_FILE"))"
else
  echo "==> Starting status server on port $PORT"
  python3 "$ROOT/deploy/status_server.py" >"$LOG_DIR/status-server.log" 2>&1 &
  echo $! >"$PID_FILE"
  sleep 1
fi

echo "==> Starting Cloudflare Quick Tunnel (temporary *.trycloudflare.com URL)"
echo "    Endpoints: /health  /status/{job_id}"
echo "    Press Ctrl+C to stop."
echo ""

cloudflared tunnel --url "http://localhost:${PORT}" 2>&1 | tee "$LOG_DIR/quick-tunnel.log"
