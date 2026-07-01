#!/usr/bin/env bash
# End-to-end test: local pipeline stack + Cloudflare quick tunnel + enqueue + poll status.
#
# Usage:
#   ./deploy/test-full-flow.sh /path/to/invoice.pdf
#   ./deploy/test-full-flow.sh /path/to/invoice.pdf --start-stack   # also start MySQL + 6 containers
#   ./deploy/test-full-flow.sh /path/to/invoice.pdf --timeout 300
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${STATUS_PORT:-8765}"
LOG_DIR="$ROOT/deploy/cloudflare/logs"
PID_FILE="$ROOT/deploy/cloudflare/.status-server.pid"
TUNNEL_PID_FILE="$ROOT/deploy/cloudflare/.tunnel.pid"
TUNNEL_LOG="$LOG_DIR/quick-tunnel.log"
TUNNEL_URL_FILE="$ROOT/deploy/cloudflare/TUNNEL_URL.txt"

START_STACK=false
TIMEOUT=180
INVOICE=""

usage() {
  sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage 0 ;;
    --start-stack) START_STACK=true; shift ;;
    --timeout) TIMEOUT="${2:?--timeout requires seconds}"; shift 2 ;;
    -*) echo "Unknown option: $1" >&2; usage 1 ;;
    *)
      if [[ -z "$INVOICE" ]]; then INVOICE="$1"; else echo "Unexpected arg: $1" >&2; usage 1; fi
      shift
      ;;
  esac
done

[[ -n "$INVOICE" ]] || usage 1
INVOICE="$(cd "$(dirname "$INVOICE")" 2>/dev/null && pwd)/$(basename "$INVOICE")" || true
[[ -f "$INVOICE" ]] || { echo "File not found: $INVOICE" >&2; exit 1; }

mkdir -p "$LOG_DIR"

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "Missing required command: $1" >&2; exit 1; }
}

need_cmd docker
need_cmd python3
need_cmd cloudflared
need_cmd curl

[[ -f "$ROOT/.env" ]] || { echo "Missing .env in project root" >&2; exit 1; }

wait_mysql() {
  echo "==> Waiting for MySQL..."
  for _ in $(seq 1 30); do
    docker exec gaadikharcha-mysql mysqladmin ping -h 127.0.0.1 -uroot -p1234 --silent 2>/dev/null && return 0
    sleep 2
  done
  echo "MySQL did not become ready" >&2
  exit 1
}

start_stack() {
  echo "==> Starting MySQL + 6 pipeline containers"
  cd "$ROOT"
  docker compose up -d mysql
  wait_mysql
  docker compose -f docker-compose.yml -f docker-compose.functions.yml up -d stage1 stage2 stage3 stage4 stage5 stage6
  docker compose -f docker-compose.yml -f docker-compose.functions.yml ps
}

ensure_status_server() {
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "==> Status server already running (pid $(cat "$PID_FILE"))"
    return
  fi
  echo "==> Starting status server on port $PORT"
  python3 "$ROOT/deploy/status_server.py" >"$LOG_DIR/status-server.log" 2>&1 &
  echo $! >"$PID_FILE"
  for _ in $(seq 1 10); do
    curl -sf "http://localhost:${PORT}/health" >/dev/null 2>&1 && return 0
    sleep 1
  done
  echo "Status server failed to start. See $LOG_DIR/status-server.log" >&2
  exit 1
}

read_tunnel_url() {
  if [[ -f "$TUNNEL_LOG" ]]; then
    grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | tail -1 || true
  fi
}

ensure_tunnel() {
  local existing
  existing="$(read_tunnel_url)"
  if pgrep -f "cloudflared tunnel --url http://localhost:${PORT}" >/dev/null 2>&1; then
    if [[ -n "$existing" ]]; then
      echo "==> Cloudflare tunnel already running: $existing"
      echo "$existing" >"$TUNNEL_URL_FILE"
      return
    fi
    echo "==> Tunnel process running; waiting for URL in log..."
  else
    echo "==> Starting Cloudflare quick tunnel (background)"
    : >"$TUNNEL_LOG"
    cloudflared tunnel --url "http://localhost:${PORT}" >>"$TUNNEL_LOG" 2>&1 &
    echo $! >"$TUNNEL_PID_FILE"
  fi

  for _ in $(seq 1 30); do
    existing="$(read_tunnel_url)"
    if [[ -n "$existing" ]]; then
      echo "==> Tunnel URL: $existing"
      echo "$existing" >"$TUNNEL_URL_FILE"
      # Give cloudflared a moment to register the route
      sleep 3
      return
    fi
    sleep 2
  done
  echo "Tunnel URL not found in $TUNNEL_LOG" >&2
  exit 1
}

enqueue_job() {
  python3 "$ROOT/deploy/test-enqueue.py" "$INVOICE"
}

poll_status() {
  local job_id="$1"
  local tunnel_url="$2"
  local elapsed=0
  local interval=5
  local status=""

  echo ""
  echo "==> Polling status (timeout ${TIMEOUT}s)"
  echo "    Local:  http://localhost:${PORT}/status/${job_id}"
  echo "    Public: ${tunnel_url}/status/${job_id}"
  echo ""

  while [[ "$elapsed" -lt "$TIMEOUT" ]]; do
    status="$(curl -sf "${tunnel_url}/status/${job_id}" 2>/dev/null || curl -sf "http://localhost:${PORT}/status/${job_id}" 2>/dev/null || true)"
    if [[ -n "$status" ]]; then
      local state
      state="$(echo "$status" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null || true)"
      local stage
      stage="$(echo "$status" | python3 -c "import sys,json; print(json.load(sys.stdin).get('current_stage',''))" 2>/dev/null || true)"
      printf '[%3ds] status=%-12s stage=%s\n' "$elapsed" "${state:-?}" "${stage:-?}"
      if [[ "$state" == "done" || "$state" == "failed" ]]; then
        echo ""
        echo "$status" | python3 -m json.tool
        return 0
      fi
    else
      printf '[%3ds] waiting for status API...\n' "$elapsed"
    fi
    sleep "$interval"
    elapsed=$((elapsed + interval))
  done

  echo "Timed out after ${TIMEOUT}s" >&2
  docker exec gaadikharcha-mysql mysql -uroot -p1234 -e \
    "USE expenses; SELECT job_id, status, current_stage, category, expense_row_id, LEFT(IFNULL(error_message,''),120) AS err FROM stage_tracking WHERE job_id='${job_id}';" 2>/dev/null || true
  exit 1
}

show_expense_row() {
  local job_id="$1"
  local category
  category="$(docker exec gaadikharcha-mysql mysql -uroot -p1234 -N -e \
    "USE expenses; SELECT category FROM stage_tracking WHERE job_id='${job_id}';" 2>/dev/null || true)"
  category="${category:-unknown}"
  local table
  case "$category" in
    Fuel) table=fuel ;;
    Maintenance) table=maintenance ;;
    Toll) table=toll ;;
    *) table="" ;;
  esac
  if [[ -n "$table" ]]; then
    echo ""
    echo "==> Expense row ($table)"
    docker exec gaadikharcha-mysql mysql -uroot -p1234 -e \
      "USE expenses; SELECT * FROM ${table} WHERE job_id='${job_id}'\\G" 2>/dev/null | head -30 || true
  fi
}

# --- main ---
echo "==> Full flow test"
echo "    Invoice: $INVOICE"

if $START_STACK; then
  start_stack
else
  docker ps --format '{{.Names}}' | grep -q '^gaadikharcha-mysql$' || {
    echo "MySQL container not running. Use --start-stack or: docker compose up -d mysql" >&2
    exit 1
  }
fi

ensure_status_server
ensure_tunnel
TUNNEL_URL="$(cat "$TUNNEL_URL_FILE")"

echo ""
echo "==> Enqueueing job"
ENQUEUE_OUT="$(enqueue_job)"
echo "$ENQUEUE_OUT"
JOB_ID="$(echo "$ENQUEUE_OUT" | awk '/^job_id:/ {print $2}')"
[[ -n "$JOB_ID" ]] || { echo "Failed to parse job_id from enqueue output" >&2; exit 1; }

poll_status "$JOB_ID" "$TUNNEL_URL"
show_expense_row "$JOB_ID"

echo ""
echo "==> Done"
echo "    job_id:     $JOB_ID"
echo "    tunnel:     $TUNNEL_URL"
echo "    status API: ${TUNNEL_URL}/status/${JOB_ID}"
