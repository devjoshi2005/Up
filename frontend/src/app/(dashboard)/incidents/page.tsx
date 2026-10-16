"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { StatusBadge } from "../page";

type Incident = { id: string; dedup_key: string; service_name: string; status: string; created_at: string };

export default function IncidentsPage() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [status, setStatus] = useState("ALL");

  useEffect(() => {
    const params = status === "ALL" ? "" : `?status=${status}`;
    api.get(`/incidents/${params}`).then((r) => setIncidents(r.data));
  }, [status]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Incidents</h1>
        <Select value={status} onValueChange={(value) => setStatus(value ?? "ALL")}>
          <SelectTrigger className="w-40"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="ALL">All</SelectItem>
            <SelectItem value="OPEN">Open</SelectItem>
            <SelectItem value="ACKED">Acknowledged</SelectItem>
            <SelectItem value="RESOLVED">Resolved</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <Card>
        <CardHeader><CardTitle>All incidents</CardTitle></CardHeader>
        <CardContent>
          <table className="w-full text-sm">
            <thead className="text-left text-slate-500 border-b">
              <tr><th className="pb-2">Service</th><th className="pb-2">Dedup Key</th>
                <th className="pb-2">Status</th><th className="pb-2">Created</th><th /></tr>
            </thead>
            <tbody>
              {incidents.map((i) => (
                <tr key={i.id} className="border-b last:border-0">
                  <td className="py-2 font-medium">{i.service_name}</td>
                  <td className="py-2 text-slate-500 truncate max-w-[220px]">{i.dedup_key}</td>
                  <td className="py-2"><StatusBadge status={i.status} /></td>
                  <td className="py-2 text-slate-500">{new Date(i.created_at).toLocaleString()}</td>
                  <td className="py-2 text-right"><Link className="text-blue-600 text-xs hover:underline" href={`/incidents/${i.id}`}>Trace</Link></td>
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