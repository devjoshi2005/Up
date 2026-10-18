"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import { api, apiErrorMessage } from "@/lib/api";
import { useTenantSocket } from "@/lib/ws";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AlertTriangle, CheckCircle2, Clock, Inbox, type LucideIcon } from "lucide-react";

type Analytics = {
  total_incidents: number; acked_incidents: number; ack_rate: number;
  mtta_seconds: number | null; mttr_seconds: number | null;
  noisiest_services: { service_name: string; count: number }[];
};
type Incident = {
  id: string; dedup_key: string; service_name: string;
  status: string; created_at: string; acked_at: string | null;
};

function fmtSec(s: number | null) {
  if (s == null) return "—";
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  return `${(s / 3600).toFixed(1)}h`;
}

export default function DashboardHome() {
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.get("/analytics/?days=7")
      .then((r) => { setAnalytics(r.data); setError(null); })
      .catch((err) => setError(apiErrorMessage(err, "the dashboard")));
    api.get("/incidents/?limit=10")
      .then((r) => setIncidents(r.data))
      .catch((err) => setError(apiErrorMessage(err, "the dashboard")));
  }, []);

  useEffect(load, [load]);

  const { connected } = useTenantSocket((e) => {
    if (e.kind === "incident.created" && e.incident) {
      toast.warning(`New incident: ${e.incident.service_name}`, {
        description: e.incident.dedup_key,
      });
    } else if (e.kind === "incident.acked" && e.incident) {
      toast.success(`Acknowledged: ${e.incident.service_name}`);
    } else if (e.kind === "incident.escalated" && e.incident) {
      toast.warning(`Escalated: ${e.incident.service_name}`, {
        description: e.notification ? `→ ${e.notification.channel}` : undefined,
      });
    } else if (e.kind === "incident.resolved" && e.incident) {
      toast.success(`Resolved: ${e.incident.service_name}`);
    }
    load();
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-bold">Overview — last 7 days</h1>
        <span
          className={`inline-flex items-center gap-1.5 text-xs px-2 py-1 rounded-full ${
            connected ? "bg-green-100 text-green-700" : "bg-slate-200 text-slate-600"
          }`}
          title={connected ? "Live updates connected" : "Reconnecting…"}
        >
          <span
            className={`w-2 h-2 rounded-full ${
              connected ? "bg-green-500" : "bg-slate-400"
            }`}
          />
          {connected ? "Live" : "Offline"}
        </span>
      </div>

      {error && (
        <p className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-md px-3 py-2">
          {error}
        </p>
      )}

      <div className="grid grid-cols-4 gap-4">
        <StatCard icon={AlertTriangle} label="Total Incidents" value={analytics?.total_incidents ?? "—"} />
        <StatCard icon={CheckCircle2} label="Ack Rate" value={analytics ? `${analytics.ack_rate}%` : "—"} />
        <StatCard icon={Clock} label="MTTA" value={fmtSec(analytics?.mtta_seconds ?? null)} />
        <StatCard icon={Inbox} label="MTTR" value={fmtSec(analytics?.mttr_seconds ?? null)} />
      </div>

      <Card>
        <CardHeader><CardTitle>Recent incidents</CardTitle></CardHeader>
        <CardContent>
          <table className="w-full text-sm">
            <thead className="text-left text-slate-500 border-b">
              <tr><th className="pb-2">Service</th><th className="pb-2">Dedup</th>
                <th className="pb-2">Status</th><th className="pb-2">Created</th><th /></tr>
            </thead>
            <tbody>
              {incidents.map((i) => (
                <tr key={i.id} className="border-b last:border-0">
                  <td className="py-2 font-medium">{i.service_name}</td>
                  <td className="py-2 text-slate-500 truncate max-w-[200px]">{i.dedup_key}</td>
                  <td className="py-2"><StatusBadge status={i.status} /></td>
                  <td className="py-2 text-slate-500">{new Date(i.created_at).toLocaleString()}</td>
                  <td className="py-2 text-right"><Link className="text-blue-600 text-xs hover:underline" href={`/incidents/${i.id}`}>View</Link></td>
                </tr>
              ))}
              {incidents.length === 0 && <tr><td colSpan={5} className="py-6 text-center text-slate-400">No incidents</td></tr>}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}

function StatCard({ icon: Icon, label, value }: { icon: LucideIcon; label: string; value: string | number }) {
  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex items-center justify-between mb-2">
          <p className="text-xs text-slate-500">{label}</p>
          <Icon className="w-4 h-4 text-slate-400" />
        </div>
        <p className="text-2xl font-bold">{value}</p>
      </CardContent>
    </Card>
  );
}

export function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    OPEN: "bg-amber-100 text-amber-700",
    ACKED: "bg-blue-100 text-blue-700",
    RESOLVED: "bg-green-100 text-green-700",
    PENDING: "bg-slate-100 text-slate-700",
    SENT: "bg-blue-100 text-blue-700",
    FAILED: "bg-red-100 text-red-700",
    ESCALATED: "bg-orange-100 text-orange-700",
    CANCELED: "bg-slate-100 text-slate-500",
  };
  return <span className={`text-xs px-2 py-1 rounded ${map[status] ?? "bg-slate-100"}`}>{status}</span>;
}