#!/usr/bin/env bash
# Named Cloudflare tunnel for MySQL + status API (requires cloudflared tunnel login).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TUNNEL_NAME="${TUNNEL_NAME:-gk-expense-dev}"
CONFIG="$ROOT/deploy/cloudflare/config.yml"
CRED_DIR="$HOME/.cloudflared"

if [[ ! -f "$CRED_DIR/cert.pem" ]]; then
  echo "ERROR: Run 'cloudflared tunnel login' first and authorize a Cloudflare zone."
  exit 1
fi

if [[ ! -f "$CONFIG" ]] || grep -q "REPLACE_TUNNEL_ID" "$CONFIG"; then
  echo "==> Creating tunnel: $TUNNEL_NAME"
  cloudflared tunnel create "$TUNNEL_NAME" || true
  TUNNEL_ID=$(cloudflared tunnel list --output json | python3 -c "
import json,sys,os
name=os.environ.get('TUNNEL_NAME','gk-expense-dev')
for t in json.load(sys.stdin):
    if t.get('name')==name:
        print(t['id']); break
" TUNNEL_NAME="$TUNNEL_NAME")
  CRED_FILE=$(ls "$CRED_DIR/${TUNNEL_ID}".json 2>/dev/null || ls "$CRED_DIR"/*.json | head -1)
  DOMAIN="${CF_DOMAIN:?Set CF_DOMAIN e.g. yourdomain.com}"
  sed -e "s|REPLACE_TUNNEL_ID|$TUNNEL_ID|g" \
      -e "s|REPLACE_CREDENTIALS_JSON|$CRED_FILE|g" \
      -e "s|YOUR_DOMAIN.com|$DOMAIN|g" \
      "$ROOT/deploy/cloudflare/config.yml" > "$ROOT/deploy/cloudflare/config.active.yml"
  CONFIG="$ROOT/deploy/cloudflare/config.active.yml"
  cloudflared tunnel route dns "$TUNNEL_NAME" "mysql-gk.$DOMAIN" || true
  cloudflared tunnel route dns "$TUNNEL_NAME" "status-gk.$DOMAIN" || true
  echo "==> Update Azure Function DB_HOST to mysql-gk.$DOMAIN"
fi

PORT="${STATUS_PORT:-8765}"
python3 "$ROOT/deploy/status_server.py" >"$ROOT/deploy/cloudflare/logs/status-server.log" 2>&1 &
echo $! >"$ROOT/deploy/cloudflare/.status-server.pid"

echo "==> Running named tunnel $TUNNEL_NAME"
cloudflared tunnel --config "$CONFIG" run "$TUNNEL_NAME"
