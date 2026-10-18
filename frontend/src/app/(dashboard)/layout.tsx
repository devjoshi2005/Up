"use client";
import { Suspense, useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { ROLE_LABEL, isDashboardRole, landingFor } from "@/lib/roles";
import { Button } from "@/components/ui/button";
import {
  Activity, AlertTriangle, BarChart3, BellRing, Inbox, LogOut, Send, type LucideIcon,
} from "lucide-react";

type NavItem = { href: string; label: string; icon: LucideIcon };

/** Nav is a function of the RBAC role — producers/responders get their own single console. */
function navFor(role?: string | null): NavItem[] {
  if (role === "producer") return [{ href: "/produce", label: "Produce Alert", icon: Send }];
  if (role === "responder") return [{ href: "/inbox", label: "On-Call Inbox", icon: BellRing }];
  return [
    { href: "/", label: "Dashboard", icon: Activity },
    { href: "/incidents", label: "Incidents", icon: AlertTriangle },
    { href: "/analytics", label: "Analytics", icon: BarChart3 },
    { href: "/dlq", label: "Dead Letters", icon: Inbox },
  ];
}

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { me, loading, logout } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !me) router.push("/login");
  }, [loading, me, router]);

  if (loading) return <div className="p-8 text-slate-500">Loading…</div>;
  if (!me) return null;

  const items = navFor(me.role);

  return (
    <div className="flex min-h-screen">
      <aside className="w-56 border-r bg-white p-4 flex flex-col">
        <div className="mb-8">
          <h1 className="text-xl font-bold text-slate-900">SysFlow</h1>
          <p className="text-xs text-slate-500 truncate">{me.tenant_name}</p>
        </div>
        <nav className="flex-1 space-y-1">
          {/* usePathname() reads URL data; it needs a Suspense boundary so the
              route can still prerender (see Next.js "blocking-prerender-client-hook"). */}
          <Suspense fallback={<NavList items={items} pathname={null} />}>
            <NavLinks items={items} />
          </Suspense>
        </nav>
        <div className="border-t pt-3">
          <p className="text-xs text-slate-500 truncate mb-1">{me.email}</p>
          <p className="text-[11px] uppercase tracking-wide text-slate-400 mb-2">
            {ROLE_LABEL[me.role] ?? me.role}
          </p>
          <Button variant="ghost" size="sm" onClick={() => { logout(); router.push("/login"); }}>
            <LogOut className="w-4 h-4 mr-2" /> Sign out
          </Button>
        </div>
      </aside>
      <main className="flex-1 p-8 max-w-7xl">
        <Suspense fallback={null}>
          <RoleGate />
        </Suspense>
        <Suspense fallback={<div className="p-8 text-slate-400">Loading…</div>}>
          {children}
        </Suspense>
      </main>
    </div>
  );
}

/** Keeps each persona on the surface their role is allowed to use. */
function RoleGate() {
  const { me, loading } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (loading || !me || !pathname) return;
    const onProduce = pathname.startsWith("/produce");
    const onInbox = pathname.startsWith("/inbox");
    if (me.role === "producer" && !onProduce) router.replace(landingFor(me.role));
    else if (me.role === "responder" && !onInbox) router.replace(landingFor(me.role));
    else if (isDashboardRole(me.role) && (onProduce || onInbox)) router.replace("/");
  }, [loading, me, pathname, router]);

  return null;
}

function NavLinks({ items }: { items: NavItem[] }) {
  return <NavList items={items} pathname={usePathname()} />;
}

function NavList({ items, pathname }: { items: NavItem[]; pathname: string | null }) {
  return (
    <>
      {items.map((n) => {
        const active = pathname === n.href || (n.href !== "/" && !!pathname && pathname.startsWith(n.href));
        return (
          <Link key={n.href} href={n.href}
            className={`flex items-center gap-2 px-3 py-2 rounded-md text-sm ${
              active ? "bg-slate-900 text-white" : "text-slate-700 hover:bg-slate-100"
            }`}>
            <n.icon className="w-4 h-4" />{n.label}
          </Link>
        );
      })}
    </>
  );
}
