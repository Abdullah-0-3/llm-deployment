#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost}"
API_BASE="${API_BASE:-$BASE_URL/api}"
API_KEY="${API_KEY:-adminLLM}"
POLL_ATTEMPTS="${POLL_ATTEMPTS:-20}"
POLL_DELAY_SECONDS="${POLL_DELAY_SECONDS:-2}"

log() {
  printf "\n[smoke] %s\n" "$1"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1"
    exit 1
  fi
}

json_field() {
  local json="$1"
  local field="$2"

  if command -v jq >/dev/null 2>&1; then
    printf "%s" "$json" | jq -r ".$field // empty"
    return
  fi

  python3 - "$field" "$json" <<'PY'
import json
import sys

field = sys.argv[1]
payload = json.loads(sys.argv[2])
value = payload.get(field, "")
if value is None:
    value = ""
print(value)
PY
}

require_cmd curl
require_cmd docker
require_cmd python3

log "Health check"
HEALTH_RESPONSE="$(curl -fsS "$API_BASE/")"
printf "Health: %s\n" "$HEALTH_RESPONSE"

log "Sync generate"
SYNC_RESPONSE="$(curl -fsS -X POST "$API_BASE/generate" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  --data-raw '{"prompt":"Say hello in one short sentence."}')"
SYNC_TEXT="$(json_field "$SYNC_RESPONSE" "response")"
if [ -z "$SYNC_TEXT" ]; then
  echo "Generate response is empty"
  echo "$SYNC_RESPONSE"
  exit 1
fi
printf "Generate response: %.120s\n" "$SYNC_TEXT"

log "Async submit"
SUBMIT_RESPONSE="$(curl -fsS -X POST "$API_BASE/submit" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  --data-raw '{"prompt":"Explain observability in one sentence."}')"
TASK_ID="$(json_field "$SUBMIT_RESPONSE" "task_id")"
if [ -z "$TASK_ID" ]; then
  echo "task_id not returned"
  echo "$SUBMIT_RESPONSE"
  exit 1
fi
printf "Task ID: %s\n" "$TASK_ID"

log "Async poll"
ASYNC_RESULT=""
for attempt in $(seq 1 "$POLL_ATTEMPTS"); do
  RESULT_RESPONSE="$(curl -fsS -H "X-API-Key: $API_KEY" "$API_BASE/result/$TASK_ID")"
  STATUS="$(json_field "$RESULT_RESPONSE" "status")"
  printf "Attempt %s/%s status=%s\n" "$attempt" "$POLL_ATTEMPTS" "$STATUS"

  if [ "$STATUS" = "completed" ]; then
    ASYNC_RESULT="$(python3 - "$RESULT_RESPONSE" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
result = payload.get("result") or {}
print(result.get("response", ""))
PY
)"
    break
  fi

  if [ "$STATUS" = "failed" ]; then
    echo "Async task failed"
    echo "$RESULT_RESPONSE"
    exit 1
  fi

  sleep "$POLL_DELAY_SECONDS"
done

if [ -z "$ASYNC_RESULT" ]; then
  echo "Async task did not complete in time"
  exit 1
fi
printf "Async response: %.120s\n" "$ASYNC_RESULT"

log "RAG ingest"
INGEST_RESPONSE="$(curl -fsS -X POST "$API_BASE/ingest" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  --data-raw '{"source":"smoke-tests","text":"Ollama can be deployed locally for private inference. RAG stores chunks for retrieval."}')"
CHUNKS_STORED="$(json_field "$INGEST_RESPONSE" "chunks_stored")"
if [ -z "$CHUNKS_STORED" ]; then
  echo "Ingest did not return chunks_stored"
  echo "$INGEST_RESPONSE"
  exit 1
fi
printf "Chunks stored: %s\n" "$CHUNKS_STORED"

log "RAG search"
RAG_RESPONSE="$(curl -fsS -X POST "$API_BASE/rag/search" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  --data-raw '{"query":"What does RAG store?","limit":2}')"
MATCH_COUNT="$(python3 - "$RAG_RESPONSE" <<'PY'
import json
import sys
payload = json.loads(sys.argv[1])
print(len(payload.get("matches", [])))
PY
)"
if [ "$MATCH_COUNT" -lt 1 ]; then
  echo "RAG search returned no matches"
  echo "$RAG_RESPONSE"
  exit 1
fi
printf "RAG matches: %s\n" "$MATCH_COUNT"

log "Metrics check"
METRICS_TEXT="$(curl -fsS "$API_BASE/metrics")"
if ! printf "%s" "$METRICS_TEXT" | grep -q "llm_total_tokens_total"; then
  echo "Token metric llm_total_tokens_total missing"
  exit 1
fi
printf "Metrics include llm_total_tokens_total\n"

log "Database checks"
docker compose exec -T postgres psql -U llmops -d llmops -c "SELECT COUNT(*) AS total_logs FROM llm_logs;"
docker compose exec -T postgres psql -U llmops -d llmops -c "SELECT COUNT(*) AS total_rag_chunks FROM rag_chunks;"

log "Smoke tests completed successfully"
