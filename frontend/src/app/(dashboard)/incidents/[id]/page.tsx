"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusBadge } from "../../page";
import { CircleDot, CheckCircle2, XCircle, Clock, AlertTriangle } from "lucide-react";

type Attempt = { id: string; channel: string; status: string; provider_response: string; latency_ms: number | null; attempted_at: string };
type Notification = {
  id: string; channel: string; status: string; priority: string;
  recipient_email: string; recipient_phone: string;
  subject: string; escalation_due_at: string | null;
  retry_count: number; sweeper_requeue_count: number;
  created_at: string; updated_at: string; attempts: Attempt[];
};
type Incident = {
  id: string; dedup_key: string; service_name: string; status: string; policy_name: string;
  created_at: string; acked_at: string | null; resolved_at: string | null;
  notifications: Notification[];
};

export default function IncidentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [incident, setIncident] = useState<Incident | null>(null);

  useEffect(() => {
    if (!id) return;
    api.get(`/incidents/${id}/`).then((r) => setIncident(r.data));
  }, [id]);

  if (!incident) return <p className="text-slate-500">Loading…</p>;

  const ordered = [...incident.notifications].sort(
    (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">{incident.service_name}</h1>
        <p className="text-sm text-slate-500">{incident.dedup_key}</p>
      </div>

      <div className="grid grid-cols-4 gap-4">
        <InfoTile label="Status" value={<StatusBadge status={incident.status} />} />
        <InfoTile label="Policy" value={incident.policy_name} />
        <InfoTile label="Opened" value={new Date(incident.created_at).toLocaleString()} />
        <InfoTile label="Acked" value={incident.acked_at ? new Date(incident.acked_at).toLocaleString() : "—"} />
      </div>

      <Card>
        <CardHeader><CardTitle>Delivery Trace</CardTitle></CardHeader>
        <CardContent>
          <ol className="relative border-l-2 border-slate-200 ml-2 space-y-8">
            {ordered.map((n, idx) => (
              <li key={n.id} className="ml-6">
                <span className="absolute -left-[11px] flex items-center justify-center w-5 h-5 rounded-full bg-white border-2 border-slate-300">
                  {statusIcon(n.status)}
                </span>
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-semibold text-sm">{n.channel}</span>
                  <StatusBadge status={n.status} />
                  <span className="text-xs text-slate-400">step {idx + 1}</span>
                  {n.retry_count > 0 && <span className="text-xs text-amber-600">retries: {n.retry_count}</span>}
                </div>
                <p className="text-xs text-slate-500 mb-1">
                  to {n.recipient_email || n.recipient_phone || "—"} · created {new Date(n.created_at).toLocaleTimeString()}
                </p>
                {n.escalation_due_at && (
                  <p className="text-xs text-slate-400 mb-2">escalation due {new Date(n.escalation_due_at).toLocaleTimeString()}</p>
                )}
                <div className="space-y-1">
                  {n.attempts.map((a) => (
                    <div key={a.id} className="text-xs text-slate-600 flex items-center gap-2">
                      <span className={a.status === "SENT" ? "text-green-600" : "text-red-600"}>●</span>
                      <span>{a.status}</span>
                      {a.latency_ms != null && <span className="text-slate-400">{a.latency_ms}ms</span>}
                      {a.provider_response && <span className="text-slate-400 truncate max-w-[280px]">{a.provider_response}</span>}
                      <span className="text-slate-400">{new Date(a.attempted_at).toLocaleTimeString()}</span>
                    </div>
                  ))}
                </div>
              </li>
            ))}
            {ordered.length === 0 && <li className="ml-6 text-sm text-slate-400">No notifications dispatched yet.</li>}
          </ol>
        </CardContent>
      </Card>
    </div>
  );
}

function InfoTile({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <Card><CardContent className="pt-6">
      <p className="text-xs text-slate-500 mb-1">{label}</p>
      <div className="text-sm font-medium">{value}</div>
    </CardContent></Card>
  );
}

function statusIcon(status: string) {
  switch (status) {
    case "SENT": case "DELIVERED": return <CheckCircle2 className="w-3 h-3 text-green-600" />;
    case "FAILED": return <XCircle className="w-3 h-3 text-red-600" />;
    case "ESCALATED": return <AlertTriangle className="w-3 h-3 text-orange-600" />;
    case "CANCELED": return <XCircle className="w-3 h-3 text-slate-400" />;
    case "PENDING": return <Clock className="w-3 h-3 text-slate-500" />;
    default: return <CircleDot className="w-3 h-3 text-slate-400" />;
  }
}