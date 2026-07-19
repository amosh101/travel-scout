"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { apiFetch, ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth-context";

type NavItem = { href: string; label: string };

const NAV: NavItem[] = [
  { href: "/admin", label: "Overview" },
  { href: "/admin/users", label: "Users" },
  { href: "/admin/weights", label: "Algo weights" },
  { href: "/admin/sources", label: "Sources" },
  { href: "/admin/audit", label: "Audit log" },
  { href: "/admin/queue", label: "Agent queue" },
];

/**
 * Admin layout. JWT + role check happens here:
 *   - No token  → push to /auth/login
 *   - Token but /api/admin/users returns 403 → show "Access denied"
 *   - Otherwise → render children
 *
 * The backend independently enforces Tailscale CIDR gating (separate
 * concern) and per-permission guards (per-endpoint). This front-end
 * guard is a UX nicety, not a security boundary.
 */
export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { token, ready, setToken } = useAuth();

  const [verified, setVerified] = useState(false);
  const [denied, setDenied] = useState(false);
  const [me, setMe] = useState<{ email: string; name: string; roles: string[] } | null>(null);

  // Auth + permission gate
  useEffect(() => {
    if (!ready) return;
    if (!token) {
      router.replace("/auth/login");
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        // Use the users list as our "do I have users.read?" probe.
        // It returns a small payload (limit=1) and exercises the gate.
        const data = await apiFetch<{
          items: { id: string; email: string; name: string; roles: string[] }[];
        }>("/api/admin/users?limit=1");
        if (cancelled) return;
        // We don't actually need the items — we just needed a 200.
        // Fetch our own user record to show the header.
        if (data.items && data.items.length > 0) {
          setMe({
            email: data.items[0].email,
            name: data.items[0].name,
            roles: data.items[0].roles,
          });
        }
        setVerified(true);
      } catch (e) {
        if (cancelled) return;
        if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
          setDenied(true);
          setVerified(true);
        } else {
          // Network / 5xx — show as denied-ish, but allow retry
          setDenied(true);
          setVerified(true);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ready, token, router]);

  // Fetch the current admin's own record (we don't have a /me endpoint yet,
  // so reuse the first item from the probe; this works because the admin
  // is typically near the top of the list).
  useEffect(() => {
    if (!verified || denied) return;
    // Re-fetch with a higher limit to get the admin's own row.
    // The bootstrap admin is amos@local.test; the first row in
    // default sort is usually them. This is good enough for a header
    // display; a proper /me endpoint is a v2.x follow-up.
    (async () => {
      try {
        const data = await apiFetch<{
          items: { id: string; email: string; name: string; roles: string[] }[];
        }>("/api/admin/users?limit=50");
        // We don't know which row is "us" from the JWT alone (no /me),
        // so we leave the header user-less unless we already populated it.
        if (data.items && data.items.length > 0 && !me) {
          // Pick the row with the most roles — usually the superadmin.
          const candidate = [...data.items].sort(
            (a, b) => b.roles.length - a.roles.length
          )[0];
          setMe({
            email: candidate.email,
            name: candidate.name,
            roles: candidate.roles,
          });
        }
      } catch {
        // Non-fatal; the header just shows "Admin"
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [verified, denied]);

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
            You don&apos;t have <code className="rounded bg-muted px-1">users.read</code>{" "}
            permission, or this panel is only available from the Tailscale network.
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

  return (
    <div className="flex min-h-screen bg-background">
      <aside className="w-60 border-r border-border bg-card p-6">
        <h2 className="text-lg font-semibold">Admin</h2>
        <p className="mt-1 text-xs text-muted-foreground">Travel Scout</p>
        <nav className="mt-6 space-y-1 text-sm">
          {NAV.map((item) => {
            const active =
              item.href === "/admin"
                ? pathname === "/admin"
                : pathname?.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`block rounded px-2 py-1.5 transition ${
                  active
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
              <div className="mt-1 text-muted-foreground">
                {me.roles.join(", ")}
              </div>
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
