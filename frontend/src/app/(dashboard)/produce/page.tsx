"use client";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { api, apiErrorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { canProduce } from "@/lib/roles";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Send } from "lucide-react";

type Step = { step_order: number; channel: string; delay_minutes: number; target: string | null };
type Policy = { id: string; name: string; steps: Step[] };
type ProducerMeta = { policies: Policy[]; example_curl: string };

export default function ProducePage() {
  const { me } = useAuth();
  const allowed = canProduce(me?.role);

  const [meta, setMeta] = useState<ProducerMeta | null>(null);
  const [policyId, setPolicyId] = useState("");
  const [serviceName, setServiceName] = useState("payments-service");
  const [eventType, setEventType] = useState("payment_failed");
  const [dedupKey, setDedupKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [lastIncident, setLastIncident] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!allowed) return;
    api.get<ProducerMeta>("/demo/producer/")
      .then((r) => {
        setMeta(r.data);
        setPolicyId((cur) => cur || r.data.policies[0]?.id || "");
        setError(null);
      })
      .catch((err) => setError(apiErrorMessage(err, "the producer console")));
  }, [allowed]);

  useEffect(load, [load]);

  const send = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const r = await api.post("/demo/produce/", {
        service_name: serviceName,
        event_type: eventType,
        dedup_key: dedupKey || undefined,
        policy_id: policyId || undefined,
      });
      setLastIncident(r.data.incident_id);
      toast.success("Alert emitted", {
        description: r.data.incident_created
          ? `Incident ${r.data.incident_id} opened — first escalation step queued.`
          : `Deduped onto existing incident ${r.data.incident_id}.`,
      });
    } catch (err) {
      toast.error("Could not emit alert", {
        description: apiErrorMessage(err, "the event pipeline"),
      });
    } finally {
      setBusy(false);
    }
  };

  if (!allowed) {
    return <p className="text-slate-500">Your role ({me?.role}) cannot produce alerts.</p>;
  }

  const selected = meta?.policies.find((p) => p.id === policyId);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Produce an alert</h1>
        <p className="text-sm text-slate-500">
          Emits an event into the same pipeline as <span className="font-mono">POST /api/v1/events/</span>:
          dedupe → incident → first escalation step.
        </p>
      </div>

      {error && (
        <p className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-md px-3 py-2">
          {error}
        </p>
      )}

      <div className="grid md:grid-cols-2 gap-6">
        <Card>
          <CardHeader><CardTitle>New event</CardTitle></CardHeader>
          <CardContent>
            <form onSubmit={send} className="space-y-4">
              <div className="space-y-2">
                <Label>Service</Label>
                <Input value={serviceName} onChange={(e) => setServiceName(e.target.value)} required />
              </div>
              <div className="space-y-2">
                <Label>Event type</Label>
                <Input value={eventType} onChange={(e) => setEventType(e.target.value)} required />
              </div>
              <div className="space-y-2">
                <Label>Dedup key <span className="text-slate-400">(optional)</span></Label>
                <Input
                  value={dedupKey}
                  onChange={(e) => setDedupKey(e.target.value)}
                  placeholder={`${serviceName}:${eventType}`}
                />
              </div>
              <div className="space-y-2">
                <Label>Escalation policy</Label>
                <Select value={policyId} onValueChange={(v) => setPolicyId(v ?? "")}>
                  <SelectTrigger><SelectValue placeholder="Select a policy" /></SelectTrigger>
                  <SelectContent>
                    {meta?.policies.map((p) => (
                      <SelectItem key={p.id} value={p.id}>{p.name}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <Button type="submit" disabled={busy || !!error}>
                <Send className="w-4 h-4 mr-1" /> {busy ? "Emitting…" : "Emit alert"}
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>What happens next</CardTitle></CardHeader>
          <CardContent className="space-y-3 text-sm">
            {selected ? (
              <ol className="space-y-2">
                {selected.steps.map((s) => (
                  <li key={s.step_order} className="flex items-start gap-2">
                    <span className="text-xs bg-slate-100 rounded px-1.5 py-0.5">{s.step_order}</span>
                    <span>
                      <span className="font-medium">{s.channel}</span> → {s.target ?? "—"}
                      <span className="text-slate-400"> (+{s.delay_minutes}m)</span>
                    </span>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="text-slate-400">Select a policy to preview its steps.</p>
            )}

            {lastIncident && (
              <p className="text-xs text-slate-500">
                Last incident: <span className="font-mono">{lastIncident}</span> — find it on the
                Incidents page or in the responder&apos;s inbox.
              </p>
            )}

            <details className="pt-2">
              <summary className="cursor-pointer text-xs text-slate-500">
                Real integration: X-API-Key
              </summary>
              <pre className="mt-2 text-[11px] bg-slate-900 text-slate-100 p-3 rounded overflow-x-auto">
{meta?.example_curl ?? "…"}
              </pre>
            </details>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
