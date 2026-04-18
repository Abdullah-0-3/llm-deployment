#!/usr/bin/env bash
set -euo pipefail

API_URL="${API_URL:-http://localhost/api/generate}"
API_KEY="${API_KEY:-adminLLM}"

if [ $# -eq 0 ]; then
  echo "Usage: ./run.sh \"your prompt here\""
  exit 1
fi

PROMPT="$*"

RAW_RESPONSE="$(curl -s -X POST "$API_URL" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  --data-raw "$(printf '{"prompt":"%s"}' "${PROMPT//\"/\\\"}")")"

if command -v jq >/dev/null 2>&1; then
  echo "$RAW_RESPONSE" | jq -r '.response // .detail // ""'
else
  echo "$RAW_RESPONSE" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("response") or d.get("detail") or "")'
fi