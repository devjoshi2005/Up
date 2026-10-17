#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."   # run from repo root so `docker compose` finds the file

API_KEY="${SYSFLOW_API_KEY:?}"
POLICY_ID="${SYSFLOW_POLICY_ID:?}"
BASE="${BASE_URL:-http://localhost:8000}"
DUP_KEY="dup-storm-$(date +%s)"
N="${N:-500}"

echo "==> firing $N requests with identical Idempotency-Key=$DUP_KEY"
for i in $(seq 1 $N); do
  curl -s -o /dev/null \
    -X POST "$BASE/api/v1/events/" \
    -H "X-API-Key: $API_KEY" \
    -H "Idempotency-Key: $DUP_KEY" \
    -H "Content-Type: application/json" \
    -d "{\"event_type\":\"dup\",\"service_name\":\"dup-svc\",\"policy_id\":\"$POLICY_ID\",\"payload\":{}}" &
done
wait

echo "==> counting events with that key (should be exactly 1)"
docker compose exec -T postgres psql -U postgres -d postgres -c "
  SELECT COUNT(*) AS events_with_key FROM events WHERE idempotency_key='$DUP_KEY';
"
