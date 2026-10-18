import http from 'k6/http';

// Local RFC-4122 v4 UUID generator. We deliberately do NOT import
// https://jslib.k6.io/... — CI/sandboxes are often offline, and a failed
// remote import aborts the whole run at init time.
function uuidv4() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

export const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
export const WS_URL   = __ENV.WS_URL   || 'ws://localhost:8000/ws/notifications';
export const API_KEY  = __ENV.SYSFLOW_API_KEY;
export const POLICY_ID = __ENV.SYSFLOW_POLICY_ID;
export const RECIPIENT_ID = __ENV.SYSFLOW_RECIPIENT_ID;

// Validate lazily per-script: ws_fanout only needs API_KEY + RECIPIENT_ID,
// while ingest/e2e also need POLICY_ID. A top-level throw breaks ws_fanout.
export function requireApiKey() {
  if (!API_KEY) throw new Error('Set SYSFLOW_API_KEY env var');
}

export function requirePolicy() {
  requireApiKey();
  if (!POLICY_ID) throw new Error('Set SYSFLOW_POLICY_ID env var');
}

export function newIdempotencyKey() {
  return uuidv4();
}

export function postEvent(
  serviceName = 'payments-service',
  eventType = 'error_rate_high',
  dedupKey = uuidv4(),
) {
  requirePolicy();
  const payload = JSON.stringify({
    event_type: eventType,
    service_name: serviceName,
    policy_id: POLICY_ID,
    // Unique per event by default, so each event opens a fresh incident +
    // notification. The E2E test waits on that notification's WS push, and the
    // ingest test exercises the full incident-creation path.
    dedup_key: dedupKey,
    payload: { rate: 0.05, source: 'k6' },
  });
  return http.post(`${BASE_URL}/api/v1/events/`, payload, {
    headers: {
      'Content-Type': 'application/json',
      'X-API-Key': API_KEY,
      'Idempotency-Key': newIdempotencyKey(),
    },
  });
}

export function fetchWsToken() {
  requireApiKey();
  if (!RECIPIENT_ID) throw new Error('Set SYSFLOW_RECIPIENT_ID env var');
  const r = http.post(
    `${BASE_URL}/api/v1/recipients/${RECIPIENT_ID}/ws-token/`,
    null,
    { headers: { 'X-API-Key': API_KEY } }
  );
  if (r.status !== 200) throw new Error(`ws-token failed: ${r.status} ${r.body}`);
  return r.json('token');
}
