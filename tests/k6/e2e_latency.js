import ws from 'k6/ws';
import { check } from 'k6';
import { Trend } from 'k6/metrics';
import { postEvent, fetchWsToken, WS_URL } from './common.js';

const e2eLatency = new Trend('e2e_latency_ms', true);

// LITE=1 runs a short, low-VU profile through the *same* code path.
const LITE = __ENV.LITE === '1';

export const options = {
  vus: LITE ? 5 : 20,
  duration: LITE ? '45s' : '3m',
  thresholds: { 'e2e_latency_ms': ['p(95)<800'] },
};

// k6 v2 forbids HTTP in the init context, so fetch the WS token in setup().
export function setup() {
  return { token: fetchWsToken() };
}

export default function (data) {
  // Each VU opens a WS, fires one event, waits for push
  const url = `${WS_URL}/?token=${data.token}`;
  const sentAt = Date.now();

  ws.connect(url, {}, function (socket) {
    socket.on('open', () => {
      postEvent();
    });
    socket.on('message', (msg) => {
      try {
        const data = JSON.parse(msg);
        // Only count a *live* push for the event THIS iteration fired.
        // - type=replay is the consumer's connect-time backlog (old created_at).
        // - backlog/requeued notifications (sweep_stuck_pending) also carry old
        //   created_at values and would otherwise show as minutes/hours.
        if (data.type !== 'notification') return;
        const sent = data.payload?.sent_at || sentAt;
        if (sent < sentAt - 2000) return;
        e2eLatency.add(Date.now() - sent);
        socket.close();
      } catch (_) {}
    });
    socket.setTimeout(() => socket.close(), 10000);
  });
}