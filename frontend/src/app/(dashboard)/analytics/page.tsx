"use client";
import { useEffect, useState } from "react";
import { api, apiErrorMessage } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell, Legend } from "recharts";

type Analytics = {
  window_days: number; total_incidents: number; acked_incidents: number;
  ack_rate: number; mtta_seconds: number | null; mttr_seconds: number | null;
  noisiest_services: { service_name: string; count: number }[];
  channel_breakdown: { channel: string; total: number; sent: number; failed: number }[];
  daily_volume: { day: string; count: number }[];
};

const COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#ef4444"];

export default function AnalyticsPage() {
  const [data, setData] = useState<Analytics | null>(null);
  const [days, setDays] = useState(7);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.get(`/analytics/?days=${days}`)
      .then((r) => { setData(r.data); setError(null); })
      .catch((err) => setError(apiErrorMessage(err, "analytics")));
  }, [days]);

  if (error) {
    return <p className="text-sm text-red-700 bg-red-50 border border-red-200 rounded-md px-3 py-2">{error}</p>;
  }
  if (!data) return <p className="text-slate-500">Loading…</p>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Analytics</h1>
        <select className="border rounded px-2 py-1 text-sm" value={days}
          onChange={(e) => setDays(Number(e.target.value))}>
          <option value={1}>Last 24h</option>
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
        </select>
      </div>

      <div className="grid grid-cols-2 gap-6">
        <Card>
          <CardHeader><CardTitle>Daily incident volume</CardTitle></CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={data.daily_volume}>
                <XAxis dataKey="day" fontSize={12} />
                <YAxis fontSize={12} />
                <Tooltip />
                <Bar dataKey="count" fill="#3b82f6" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Channel breakdown</CardTitle></CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie data={data.channel_breakdown} dataKey="total" nameKey="channel"
                  innerRadius={50} outerRadius={90} paddingAngle={3}>
                  {data.channel_breakdown.map((_, i) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
                <Legend /><Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardTitle>Noisiest services</CardTitle></CardHeader>
        <CardContent>
          <table className="w-full text-sm">
            <thead className="text-left text-slate-500 border-b">
              <tr><th className="pb-2">Service</th><th className="pb-2">Incidents</th></tr>
            </thead>
            <tbody>
              {data.noisiest_services.map((s) => (
                <tr key={s.service_name} className="border-b last:border-0">
                  <td className="py-2 font-medium">{s.service_name}</td>
                  <td className="py-2">{s.count}</td>
                </tr>
              ))}
              {data.noisiest_services.length === 0 &&
                <tr><td colSpan={2} className="py-6 text-center text-slate-400">No data</td></tr>}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}