#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."   # run from repo root so `docker compose` finds the file

API_KEY="${SYSFLOW_API_KEY:?set SYSFLOW_API_KEY}"
POLICY_ID="${SYSFLOW_POLICY_ID:?set SYSFLOW_POLICY_ID}"
BASE="${BASE_URL:-http://localhost:8000}"
WORKER="${WORKER_SVC:-celery_worker}"
EVENTS="${EVENTS:-500}"

echo "==> firing $EVENTS events while killing worker mid-flight"
(
  for i in $(seq 1 $EVENTS); do
    curl -s -o /dev/null -w "%{http_code}\n" \
      -X POST "$BASE/api/v1/events/" \
      -H "X-API-Key: $API_KEY" \
      -H "Idempotency-Key: $(uuidgen)" \
      -H "Content-Type: application/json" \
      -d "{\"event_type\":\"chaos\",\"service_name\":\"chaos-svc\",\"policy_id\":\"$POLICY_ID\",\"payload\":{\"n\":$i}}" &
  done
) &
LOAD_PID=$!

sleep 3
echo "==> docker compose kill $WORKER"
docker compose kill "$WORKER"
sleep 5
echo "==> docker compose up -d $WORKER"
docker compose up -d "$WORKER"

wait $LOAD_PID
sleep 30   # let sweeper requeue and workers finish

echo "==> checking for lost or stuck notifications"
docker compose exec -T postgres psql -U postgres -d postgres -c "
  SELECT
    (SELECT COUNT(*) FROM notifications WHERE status='PENDING') AS stuck_pending,
    (SELECT COUNT(*) FROM notifications WHERE status='FAILED') AS failed,
    (SELECT COUNT(*) FROM notifications) AS total;
"

echo "==> DLQ rows (should be 0 unless genuine provider errors):"
docker compose exec -T postgres psql -U postgres -d postgres -c "
  SELECT reason, COUNT(*) FROM dead_letters GROUP BY reason ORDER BY 2 DESC;
"
