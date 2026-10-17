#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."   # run from repo root so `docker compose` finds the file

API_KEY="${SYSFLOW_API_KEY:?}"
POLICY_ID="${SYSFLOW_POLICY_ID:?}"
BASE="${BASE_URL:-http://localhost:8000}"
EVENTS="${EVENTS:-300}"

echo "==> baseline: fire $EVENTS events"
BEFORE=$(docker compose exec -T postgres psql -U postgres -d postgres -tA -c "SELECT COUNT(*) FROM notifications;")

for i in $(seq 1 $EVENTS); do
  curl -s -o /dev/null \
    -X POST "$BASE/api/v1/events/" \
    -H "X-API-Key: $API_KEY" \
    -H "Idempotency-Key: $(uuidgen)" \
    -H "Content-Type: application/json" \
    -d "{\"event_type\":\"chaos\",\"service_name\":\"chaos-redis\",\"policy_id\":\"$POLICY_ID\",\"payload\":{}}" &
done
wait

echo "==> restart redis (AOF should replay queue)"
docker compose restart redis
sleep 20

echo "==> verify no duplicate deliveries per (notification, channel)"
docker compose exec -T postgres psql -U postgres -d postgres -c "
  SELECT notification_id, channel, COUNT(*)
  FROM delivery_attempts
  WHERE status='SENT'
  GROUP BY notification_id, channel
  HAVING COUNT(*) > 1
  ORDER BY 3 DESC
  LIMIT 10;
"
echo "==> duplicate rows above = 0 means idempotent delivery held."
