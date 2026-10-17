import { check } from 'k6';
import { Trend, Rate, Counter } from 'k6/metrics';
import { postEvent } from './common.js';

const ingestLatency = new Trend('ingest_latency_ms', true);
const ingestOk      = new Rate('ingest_ok');
const ingestErrors  = new Counter('ingest_errors');

// LITE=1 runs a short, low-VU profile through the *same* code path. Use it to
// measure/verify without burst-testing or spending real provider quota; the
// default profile is the full ramp used for headline numbers.
const LITE = __ENV.LITE === '1';

export const options = {
  scenarios: {
    ramp: {
      executor: 'ramping-vus',
      startVUs: 5,
      stages: LITE
        ? [
            { duration: '10s', target: 10 },
            { duration: '20s', target: 10 },
            { duration: '10s', target: 0 },
          ]
        : [
            { duration: '30s', target: 30 },
            { duration: '2m',  target: 30 },
            { duration: '30s', target: 80 },
            { duration: '1m',  target: 80 },
            { duration: '30s', target: 0 },
          ],
    },
  },
  thresholds: {
    'ingest_latency_ms': ['p(95)<600', 'p(99)<1200'],
    'ingest_ok': ['rate>0.99'],
    'http_req_failed': ['rate<0.02'],
  },
};

export default function () {
  const res = postEvent();
  ingestLatency.add(res.timings.duration);
  const ok = res.status === 202 || res.status === 200;
  ingestOk.add(ok);
  if (!ok) ingestErrors.add(1);

  check(res, {
    'status 202/200': (r) => r.status === 202 || r.status === 200,
    'has incident_id': (r) => { try { return !!r.json('incident_id'); } catch { return false; } },
  });
}