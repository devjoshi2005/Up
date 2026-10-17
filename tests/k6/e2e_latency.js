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

const token = fetchWsToken();

export default function () {
  // Each VU opens a WS, fires one event, waits for push
  const url = `${WS_URL}/?token=${token}`;
  const sentAt = Date.now();

  ws.connect(url, {}, function (socket) {
    socket.on('open', () => {
      postEvent();
    });
    socket.on('message', (msg) => {
      try {
        const data = JSON.parse(msg);
        if (data.type === 'notification' || data.type === 'replay') {
          const sent = data.payload?.sent_at || sentAt;
          e2eLatency.add(Date.now() - sent);
          socket.close();
        }
      } catch (_) {}
    });
    socket.setTimeout(() => socket.close(), 10000);
  });
}