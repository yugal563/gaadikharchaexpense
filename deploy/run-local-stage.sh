#!/usr/bin/env bash
set -euo pipefail

STAGE="${1:?Usage: run-local-stage.sh <1-6>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGE_DIR=$(ls -d "$ROOT/pipeline/stage${STAGE}_"* | head -1)

if [[ ! -d "$STAGE_DIR" ]]; then
  echo "Stage directory not found for stage $STAGE"
  exit 1
fi

export STAGE_NUMBER="$STAGE"
export PYTHONPATH="$ROOT:${PYTHONPATH:-}"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source <(grep -v '^#' "$ROOT/.env" | sed 's/^ *//')
  set +a
fi

cd "$STAGE_DIR"
echo "Starting stage $STAGE locally from $STAGE_DIR"
func start --python
