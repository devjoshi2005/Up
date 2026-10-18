export type Role = "admin" | "operator" | "viewer" | "producer" | "responder";

/**
 * Client-side mirror of the backend RBAC (apps/api/permissions.py).
 *
 * The backend is the source of truth — these helpers only decide what the UI
 * offers. Producers/responders log in here as a demo convenience; in
 * production they authenticate with an API key / HMAC magic link and never
 * reach the dashboard.
 */

export const DASHBOARD_ROLES: Role[] = ["admin", "operator", "viewer"];

export function isAdmin(role?: string | null): boolean {
  return role === "admin";
}

/** Dashboard read surfaces (incidents, analytics, dead letters). */
export function isDashboardRole(role?: string | null): boolean {
  return !!role && (DASHBOARD_ROLES as string[]).includes(role);
}

export function isProducer(role?: string | null): boolean {
  return role === "producer";
}

export function isResponder(role?: string | null): boolean {
  return role === "responder";
}

/** Emit alerts into the pipeline. */
export function canProduce(role?: string | null): boolean {
  return role === "admin" || role === "operator" || role === "producer";
}

/** Acknowledge / escalate an open incident. */
export function canEscalate(role?: string | null): boolean {
  return role === "admin" || role === "operator" || role === "responder";
}

/** Close the incident out (RESOLVED / MTTR). */
export function canResolve(role?: string | null): boolean {
  return role === "admin" || role === "operator";
}

/** Sensitive actions: replaying/discarding dead letters. */
export function canReplayDlq(role?: string | null): boolean {
  return role === "admin";
}

/** Where a role should land after login. */
export function landingFor(role?: string | null): string {
  if (role === "producer") return "/produce";
  if (role === "responder") return "/inbox";
  return "/";
}

export const ROLE_LABEL: Record<string, string> = {
  admin: "Admin",
  operator: "Operator",
  viewer: "Viewer",
  producer: "Producer (service)",
  responder: "Responder (on-call)",
};
