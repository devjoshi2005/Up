"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

type DL = {
  id: string; notification: string; notification_channel: string; notification_subject: string;
  reason: string; last_error: string; retry_count: number;
  resolved: boolean; resolution_note: string; resolved_at: string | null; created_at: string;
};

export default function DlqPage() {
  const [rows, setRows] = useState<DL[]>([]);
  const [showResolved, setShowResolved] = useState(false);

  const load = () => {
    const params = showResolved ? "" : "?resolved=false";
    api.get(`/dlq/${params}`).then((r) => setRows(r.data.results ?? r.data));
  };

  useEffect(load, [showResolved]);

  const replay = async (id: string) => {
    await api.post(`/dlq/${id}/replay/`);
    load();
  };
  const discard = async (id: string) => {
    await api.post(`/dlq/${id}/discard/`, { note: "discarded from UI" });
    load();
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Dead Letters</h1>
        <Button variant="outline" size="sm" onClick={() => setShowResolved((s) => !s)}>
          {showResolved ? "Show unresolved" : "Show all"}
        </Button>
      </div>

      <Card>
        <CardHeader><CardTitle>Queue</CardTitle></CardHeader>
        <CardContent>
          <table className="w-full text-sm">
            <thead className="text-left text-slate-500 border-b">
              <tr>
                <th className="pb-2">Channel</th>
                <th className="pb-2">Subject</th>
                <th className="pb-2">Reason</th>
                <th className="pb-2">Retries</th>
                <th className="pb-2">State</th>
                <th className="pb-2 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-b last:border-0 align-top">
                  <td className="py-3 font-medium">{r.notification_channel}</td>
                  <td className="py-3 max-w-[240px] truncate">{r.notification_subject}</td>
                  <td className="py-3 text-xs text-slate-500 max-w-[300px]">
                    <div className="font-medium text-slate-700">{r.reason}</div>
                    {r.last_error && <div className="truncate">{r.last_error}</div>}
                  </td>
                  <td className="py-3">{r.retry_count}</td>
                  <td className="py-3">
                    {r.resolved
                      ? <Badge variant="outline" className="text-green-700">resolved</Badge>
                      : <Badge variant="destructive">unresolved</Badge>}
                  </td>
                  <td className="py-3 text-right space-x-2">
                    {!r.resolved && (
                      <>
                        <Button size="sm" variant="outline" onClick={() => replay(r.id)}>Replay</Button>
                        <Button size="sm" variant="ghost" onClick={() => discard(r.id)}>Discard</Button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
              {rows.length === 0 && <tr><td colSpan={6} className="py-6 text-center text-slate-400">Empty</td></tr>}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}