"use client";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { api, apiErrorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { canEscalate } from "@/lib/roles";
import { useTenantSocket } from "@/lib/ws";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { BellRing, CheckCheck, RefreshCw, ArrowUpRight } from "lucide-react";

type Pending = {
  id: string; channel: string; step_order: number | null;
  recipient: string | null; escalation_due_at: string | null;
};
type Row = {
  incident_id: string; service_name: string; dedup_key: string; status: string;
  policy_name: string; created_at: string; ack_token: string; pending: Pending[];
};

export default function InboxPage() {
  const { me } = useAuth();
  const allowed = canEscalate(me?.role);
  const [rows, setRows] = useState<Row[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!allowed) return;
    api.get<Row[]>("/demo/inbox/")
      .then((r) => { setRows(r.data); setError(null); })
      .catch((err) => setError(apiErrorMessage(err, "the on-call inbox")));
  }, [allowed]);

  useEffect(load, [load]);

  useTenantSocket((e) => {
    if (e.kind.startsWith("incident.")) load();
  });

  const ack = async (row: Row) => {
    setBusyId(row.incident_id);
    try {
      // The real HMAC magic link — same token that lands in the SMS/email.
      await api.get(`/ack/${row.ack_token}/`);
      toast.success(`Acknowledged ${row.service_name}`, {
        description: "Pending escalations canceled.",
      });
      load();
    } catch {
      toast.error("Could not acknowledge", { description: "Link may be expired." });
    } finally {
      setBusyId(null);
    }
  };

  const escalate = async (row: Row) => {
    setBusyId(row.incident_id);
    try {
      const r = await api.post(`/incidents/${row.incident_id}/escalate/`);
      toast.success(`Escalated ${row.service_name}`, {
        description: `→ ${r.data.channel} (step ${r.data.step_order})`,
      });
      load();
    } catch (err) {
      toast.error("Could not escalate", {
        description: apiErrorMessage(err, "the escalation"),
      });
    } finally {
      setBusyId(null);
    }
  };

  if (!allowed) {
    return <p className="text-slate-500">Your role ({me?.role}) has no on-call inbox.</p>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">On-call inbox</h1>
          <p className="text-sm text-slate-500">
            Open fires. Acknowledge if it&apos;s yours, otherwise escalate.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load}>
          <RefreshCw className="w-4 h-4 mr-1" /> Refresh
        </Button>
      </div>

      {error && (
        <p className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-md px-3 py-2">
          {error}
        </p>
      )}

      {rows.length === 0 && !error && (
        <Card><CardContent className="py-10 text-center text-slate-400">
          <BellRing className="w-6 h-6 mx-auto mb-2" />
          Nothing on fire. 🎉
        </CardContent></Card>
      )}

      {rows.map((row) => (
        <Card key={row.incident_id}>
          <CardHeader>
            <CardTitle className="flex items-center justify-between">
              <span>{row.service_name}</span>
              <span className="text-xs font-normal text-slate-500">{row.policy_name}</span>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="text-sm text-slate-500 space-y-1">
              <p className="font-mono text-xs">{row.dedup_key}</p>
              <p>Opened {new Date(row.created_at).toLocaleString()}</p>
            </div>

            <div className="flex flex-wrap gap-2">
              {row.pending.length > 0 ? (
                row.pending.map((p) => (
                  <span key={p.id} className="text-xs bg-amber-50 text-amber-700 border border-amber-200 rounded px-2 py-1">
                    step {p.step_order ?? "—"} · {p.channel}
                    {p.recipient ? ` → ${p.recipient}` : ""}
                  </span>
                ))
              ) : (
                <span className="text-xs text-slate-400">No pending notification on this step.</span>
              )}
            </div>

            <div className="flex items-center gap-2">
              <Button
                onClick={() => ack(row)}
                disabled={busyId === row.incident_id || row.pending.length === 0}
                title={row.pending.length === 0 ? "Nothing pending to acknowledge" : "Fire the magic-link ack"}
              >
                <CheckCheck className="w-4 h-4 mr-1" /> Acknowledge
              </Button>
              <Button
                variant="outline"
                onClick={() => escalate(row)}
                disabled={busyId === row.incident_id}
                title="Notify the next step in the policy immediately"
              >
                <ArrowUpRight className="w-4 h-4 mr-1" /> Escalate
              </Button>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
