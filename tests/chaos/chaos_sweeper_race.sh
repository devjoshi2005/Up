#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."   # run from repo root so `docker compose` finds the file

echo "==> firing two concurrent sweepers against the same DB"
docker compose exec -T celery_worker celery -A config call apps.notifications.tasks.sweep_escalations &
docker compose exec -T celery_worker celery -A config call apps.notifications.tasks.sweep_escalations &
wait
sleep 10

echo "==> verify no double-escalation per (incident, step_order)"
docker compose exec -T postgres psql -U postgres -d postgres -c "
  SELECT n.incident_id, s.step_order, COUNT(*)
  FROM notifications n
  JOIN escalation_steps s ON s.id = n.escalation_step_id
  WHERE n.channel IS NOT NULL
  GROUP BY n.incident_id, s.step_order
  HAVING COUNT(*) > 1
  LIMIT 10;
"
echo "==> rows above = 0 means SKIP LOCKED did its job."