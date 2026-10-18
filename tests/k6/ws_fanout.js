import ws from 'k6/ws';
import { check } from 'k6';
import { Trend, Counter } from 'k6/metrics';
import { WS_URL, fetchWsToken } from './common.js';

const wsConnecting = new Trend('ws_connecting_ms', true);
const wsErrors     = new Counter('ws_errors');

// LITE=1 runs a short, small-fanout profile through the *same* code path.
const LITE = __ENV.LITE === '1';

export const options = {
  scenarios: {
    hold: {
      executor: 'ramping-vus',
      startVUs: 10,
      stages: LITE
        ? [
            { duration: '10s', target: 30 },
            { duration: '30s', target: 30 },
            { duration: '10s', target: 0 },
          ]
        : [
            { duration: '30s', target: 100 },
            { duration: '30s', target: 300 },
            { duration: '2m',  target: 300 },
            { duration: '30s', target: 500 },
            { duration: '2m',  target: 500 },
            { duration: '30s', target: 0 },
          ],
    },
  },
  thresholds: {
    'ws_connecting_ms': ['p(95)<2000'],
    'ws_errors': ['count<50'],
  },
};

// k6 v2 forbids HTTP in the init context, so fetch the WS token in setup()
// (runs once, shared by all VUs) instead of at module top level.
export function setup() {
  return { token: fetchWsToken() };
}

export default function (data) {
  const url = `${WS_URL}/?token=${data.token}`;
  const t0 = Date.now();
  const res = ws.connect(url, {}, function (socket) {
    socket.on('open', () => {
      wsConnecting.add(Date.now() - t0);
      // hold for 90s with periodic pings
      socket.setInterval(() => socket.send(JSON.stringify({ type: 'ping' })), 15000);
    });
    socket.on('error', () => wsErrors.add(1));
    socket.setTimeout(() => socket.close(), 90000);
  });
  check(res, { 'status 101': (r) => r && r.status === 101 });
}