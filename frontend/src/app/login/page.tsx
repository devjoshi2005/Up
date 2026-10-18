"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { landingFor } from "@/lib/roles";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";

// Demo personas seeded by `manage.py shell < scripts/seed.py` (password: demo1234).
const PERSONAS = [
  { email: "producer@up.test", label: "Producer", blurb: "emits alerts (API key in prod)" },
  { email: "responder@up.test", label: "Responder", blurb: "acknowledges / escalates (magic link in prod)" },
  { email: "demo@up.test", label: "Admin", blurb: "full dashboard + resolve + DLQ" },
  { email: "op@up.test", label: "Operator", blurb: "incidents, resolve, escalate" },
  { email: "view@up.test", label: "Viewer", blurb: "read-only dashboard" },
];

export default function LoginPage() {
  const { login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      const me = await login(email, password);
      router.push(landingFor(me.role));
    } catch {
      setErr("Invalid credentials");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <div className="grid md:grid-cols-2 gap-6 w-full max-w-3xl">
        <Card>
          <CardHeader><CardTitle>Login to SysFlow</CardTitle></CardHeader>
          <CardContent>
            <form onSubmit={submit} className="space-y-4">
              <div className="space-y-2"><Label>Email</Label>
                <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required /></div>
              <div className="space-y-2"><Label>Password</Label>
                <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required /></div>
              {err && <p className="text-sm text-red-600">{err}</p>}
              <Button type="submit" className="w-full" disabled={busy}>{busy ? "Signing in..." : "Sign in"}</Button>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Demo roles</CardTitle></CardHeader>
          <CardContent className="space-y-2">
            <p className="text-xs text-slate-500">
              One click fills the form. All demo accounts use password{" "}
              <span className="font-mono">demo1234</span>.
            </p>
            {PERSONAS.map((p) => (
              <button
                key={p.email}
                type="button"
                onClick={() => { setEmail(p.email); setPassword("demo1234"); setErr(null); }}
                className="w-full text-left rounded-md border px-3 py-2 hover:bg-slate-50"
              >
                <span className="text-sm font-medium">{p.label}</span>
                <span className="block text-xs text-slate-500">
                  <span className="font-mono">{p.email}</span> — {p.blurb}
                </span>
              </button>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
