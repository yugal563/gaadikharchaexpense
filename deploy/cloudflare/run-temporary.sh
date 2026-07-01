#!/usr/bin/env bash
# Start temporary local dev stack: MySQL + 6 function containers + Cloudflare quick tunnel.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

echo "==> Starting MySQL"
docker compose up -d mysql

echo "==> Waiting for MySQL..."
for i in $(seq 1 30); do
  docker exec gaadikharcha-mysql mysqladmin ping -h 127.0.0.1 -uroot -p1234 --silent 2>/dev/null && break
  sleep 2
done

echo "==> Starting 6 local function containers"
docker compose -f docker-compose.yml -f docker-compose.functions.yml up -d stage1 stage2 stage3 stage4 stage5 stage6

echo "==> Function containers:"
docker compose -f docker-compose.yml -f docker-compose.functions.yml ps

echo ""
echo "==> Starting Cloudflare Quick Tunnel (status API)"
echo "    Submit jobs: python3 deploy/test-enqueue.py /path/to/invoice.pdf"
echo "    Check status: curl https://<trycloudflare-url>/status/<job_id>"
echo ""

exec "$ROOT/deploy/cloudflare/run-quick-tunnel.sh"
