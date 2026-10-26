"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { apiFetch, ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth-context";

type Me = {
  name: string;
  email: string;
  tier: string;
  permissions: string[];
};

/**
 * Admin layout. JWT + permission check happens here, verified against
 * /api/auth/me — the REAL identity and permission list, not a guessed
 * row from the users list:
 *   - No token            -> push to /auth/login
 *   - 401 (stale token)   -> push to /auth/login
 *   - No admin/agent perm -> "Access denied" screen
 *   - Otherwise           -> children behind a permission-filtered sidebar
 *
 * Who reaches what (mirrors the backend permission map):
 *   agent.work | agent.assign -> Overview + Agent queue
 *   user.read                  -> + Users
 *   weights.update             -> + Algo weights
 *   source.admin               -> + Sources
 *   audit.read                 -> + Audit log
 *
 * The backend independently enforces Tailscale CIDR gating (separate
 * concern) and per-endpoint guards. This front-end gate is a UX nicety,
 * not a security boundary.
 */
const FULL_NAV: { href: string; label: string; perms: string[] }[] = [
  { href: "/admin", label: "Overview", perms: [] },
  { href: "/admin/users", label: "Users", perms: ["user.read"] },
  { href: "/admin/weights", label: "Algo weights", perms: ["weights.update"] },
  { href: "/admin/sources", label: "Sources", perms: ["source.admin"] },
  { href: "/admin/interests", label: "Interest catalog", perms: ["destination.admin"] },
  { href: "/admin/audit", label: "Audit log", perms: ["audit.read"] },
  { href: "/admin/queue", label: "Agent queue", perms: ["agent.work", "agent.assign"] },
  { href: "/admin/messages", label: "Conversations", perms: ["agent.work", "agent.assign", "itinerary.read_all"] },
  { href: "/admin/reports", label: "Reports", perms: ["report.read", "agent.work"] },
];

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { token, ready, setToken } = useAuth();

  const [verified, setVerified] = useState(false);
  const [denied, setDenied] = useState(false);
  const [me, setMe] = useState<Me | null>(null);

  // Auth + permission gate — one real call to /api/auth/me.
  useEffect(() => {
    if (!ready) return;
    if (!token) {
      router.replace("/auth/login");
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const v = await apiFetch<Me>("/api/auth/me");
        if (cancelled) return;
        const perms = new Set(v.permissions ?? []);
        const allowed = ["user.read", "agent.work", "agent.assign"].some((p) =>
          perms.has(p),
        );
        setMe(v);
        setDenied(!allowed);
        setVerified(true);
      } catch (e) {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 401) {
          // Stale token — re-authenticate.
          setToken(null);
          router.replace("/auth/login");
          return;
        }
        // 5xx / network: treat as denied-ish, user can retry by reload.
        setDenied(true);
        setVerified(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ready, token, router, setToken]);

  const signOut = useCallback(() => {
    setToken(null);
    router.replace("/auth/login");
  }, [setToken, router]);

  if (!verified) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background text-muted-foreground">
        Verifying admin permissions…
      </div>
    );
  }
  if (denied) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="max-w-md rounded-2xl border border-border bg-card p-8 text-center shadow-xl">
          <h1 className="text-2xl font-semibold">Access denied</h1>
          <p className="mt-2 text-muted-foreground">
            You don&apos;t have <code className="rounded bg-muted px-1">user.read</code>{" "}
            or <code className="rounded bg-muted px-1">agent.work</code> permission, or
            this panel is only available from the Tailscale network.
          </p>
          <button
            onClick={signOut}
            className="mt-6 inline-flex items-center rounded-full border border-border bg-background px-4 py-1.5 text-sm font-medium transition hover:bg-muted"
          >
            Sign out
          </button>
        </div>
      </div>
    );
  }

  const perms = new Set(me?.permissions ?? []);
  const has = (need: string[]) => need.length === 0 || need.some((p) => perms.has(p));
  const nav = FULL_NAV.filter((item) => has(item.perms));
  const roleLabel =
    perms.has("agent.work") || perms.has("agent.assign")
      ? perms.has("user.update") || perms.has("weights.update")
        ? "Agent + admin"
        : "Booking agent"
      : "Admin";

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <aside className="w-60 border-r border-border bg-card p-6">
        <h2 className="text-lg font-semibold">Admin</h2>
        <p className="mt-1 text-xs text-muted-foreground">Travel Scout</p>
        <nav className="mt-6 space-y-1 text-sm">
          {nav.map((item) => {
            const active =
              item.href === "/admin"
                ? pathname === "/admin"
                : pathname?.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`block rounded px-2 py-1.5 transition ${active
                  ? "bg-foreground/10 font-medium text-foreground"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground"
                  }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="mt-8 border-t border-border pt-4 text-xs">
          {me ? (
            <>
              <div className="font-medium text-foreground">{me.name}</div>
              <div className="truncate text-muted-foreground">{me.email}</div>
              <div className="mt-1 text-muted-foreground">{roleLabel}</div>
            </>
          ) : (
            <div className="text-muted-foreground">Signed in</div>
          )}
          <button
            onClick={signOut}
            className="mt-3 inline-flex items-center rounded border border-border bg-background px-2 py-0.5 text-xs font-medium text-foreground transition hover:bg-muted"
          >
            Sign out
          </button>
        </div>
      </aside>
      <main className="flex-1 p-8">{children}</main>
    </div>
  );
}