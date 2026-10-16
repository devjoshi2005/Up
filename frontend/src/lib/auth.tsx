"use client";
import { createContext, useContext, useEffect, useState } from "react";
import { api, clearTokens, setTokens } from "./api";

type Me = { id: string; email: string; tenant_id: string; tenant_name: string; role: string };
type Ctx = { me: Me | null; loading: boolean; login: (e: string, p: string) => Promise<void>; logout: () => void };

const AuthContext = createContext<Ctx | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const access = typeof window !== "undefined" ? localStorage.getItem("access") : null;

    if (!access) {
      // Defer so we never setState synchronously inside the effect body.
      const t = window.setTimeout(() => {
        if (!cancelled) setLoading(false);
      }, 0);
      return () => {
        cancelled = true;
        window.clearTimeout(t);
      };
    }

    api.get<Me>("/auth/me/")
      .then((r) => {
        if (!cancelled) setMe(r.data);
      })
      .catch(() => clearTokens())
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const login = async (email: string, password: string) => {
    const r = await api.post("/auth/login/", { email, password });
    setTokens(r.data.access, r.data.refresh);
    const me = await api.get<Me>("/auth/me/");
    setMe(me.data);
  };

  const logout = () => { clearTokens(); setMe(null); };

  return <AuthContext.Provider value={{ me, loading, login, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}
