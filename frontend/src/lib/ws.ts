"use client";
import { useEffect, useRef, useState } from "react";

export type IncidentEventItem = {
  id: string;
  service_name: string;
  dedup_key: string;
  status: string;
  created_at?: string;
  acked_at?: string | null;
  resolved_at?: string | null;
};

export type DashboardEvent = {
  kind:
    | "incident.created"
    | "incident.acked"
    | "incident.escalated"
    | "incident.resolved"
    | "notification.updated";
  incident?: IncidentEventItem;
  notification?: {
    id: string;
    incident_id?: string;
    channel: string;
    status?: string;
    subject?: string;
    latency_ms?: number | null;
    step_order?: number;
  };
  canceled_notifications?: number;
};

const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000/ws";
const RECONNECT_MS = 2000;

/**
 * Live tenant feed. Connects to `/ws/dashboard/` with the current JWT access
 * token, auto-reconnects, and calls `onEvent` for every incident/notification
 * event the backend fans out to this tenant.
 */
export function useTenantSocket(onEvent: (event: DashboardEvent) => void) {
  const [connected, setConnected] = useState(false);
  const cb = useRef(onEvent);
  useEffect(() => {
    cb.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let retry: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      const token =
        typeof window !== "undefined" ? localStorage.getItem("access") : null;
      if (!token) {
        retry = setTimeout(connect, RECONNECT_MS);
        return;
      }

      ws = new WebSocket(
        `${WS_BASE}/dashboard/?token=${encodeURIComponent(token)}`
      );
      ws.onopen = () => setConnected(true);
      ws.onerror = () => ws?.close();
      ws.onclose = () => {
        setConnected(false);
        if (!closed) retry = setTimeout(connect, RECONNECT_MS);
      };
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          if (msg.type === "event") cb.current(msg.event as DashboardEvent);
        } catch {
          /* ignore malformed frames */
        }
      };
    };

    connect();
    return () => {
      closed = true;
      if (retry) clearTimeout(retry);
      ws?.close();
    };
  }, []);

  return { connected };
}
