"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiFetch, ApiError } from "../../lib/api";

type Stat = { label: string; value: string; href?: string; sub?: string };

export default function AdminOverviewPage() {
  const [stats, setStats] = useState<Stat[] | null>(null);
  const [recentAudit, setRecentAudit] = useState<
    {
      id: string;
      action: string;
      actor_user_id: string | null;
      at: string;
    }[]
  >([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [users, audit, weights, sources, queuePending] = await Promise.all([
          apiFetch<{ total: number }>("/api/admin/users?limit=1"),
          apiFetch<{ total: number; items: { id: string; action: string; actor_user_id: string | null; at: string }[] }>(
            "/api/admin/audit?limit=8"
          ),
          apiFetch<{ items: unknown[] }>("/api/admin/weights"),
          apiFetch<{ items: { enabled: boolean }[] }>("/api/admin/sources"),
          apiFetch<{ items: unknown[] }>("/api/agent/queue?status=pending"),
        ]);
        if (cancelled) return;
        const enabledSources = sources.items.filter((s) => s.enabled).length;
        setStats([
          { label: "Users", value: String(users.total), href: "/admin/users" },
          {
            label: "Audit entries",
            value: String(audit.total),
            href: "/admin/audit",
          },
          {
            label: "Algo weights",
            value: String(weights.items.length),
            href: "/admin/weights",
            sub: "scoring factors",
          },
          {
            label: "Sources",
            value: `${enabledSources}/${sources.items.length}`,
            href: "/admin/sources",
            sub: "enabled / total",
          },
          {
            label: "Booking queue",
            value: String(queuePending.items.length),
            href: "/admin/queue",
            sub: "pending",
          },
        ]);
        setRecentAudit(audit.items);
      } catch (e) {
        if (cancelled) return;
        setErr(
          e instanceof ApiError
            ? `Failed to load overview (${e.status})`
            : e instanceof Error
              ? e.message
              : "Failed to load overview"
        );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-semibold">Admin overview</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Live counts from the same API the rest of the panel uses.
        </p>
      </div>

      {err && (
        <div className="rounded-lg border border-rose-300 bg-rose-50 p-3 text-sm text-rose-900 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-200">
          {err}
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
        {stats === null
          ? Array.from({ length: 5 }).map((_, i) => (
              <div
                key={i}
                className="h-24 animate-pulse rounded-xl border border-border bg-card"
              />
            ))
          : stats.map((s) => (
              <Link
                key={s.label}
                href={s.href ?? "#"}
                className="block rounded-xl border border-border bg-card p-5 transition hover:border-foreground/30"
              >
                <div className="text-xs uppercase tracking-wide text-muted-foreground">
                  {s.label}
                </div>
                <div className="mt-1 text-3xl font-semibold tabular-nums">
                  {s.value}
                </div>
                {s.sub && (
                  <div className="mt-1 text-xs text-muted-foreground">{s.sub}</div>
                )}
              </Link>
            ))}
      </div>

      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-xl font-semibold">Recent activity</h2>
          <Link
            href="/admin/audit"
            className="text-sm text-muted-foreground hover:underline"
          >
            View all →
          </Link>
        </div>
        <div className="overflow-hidden rounded-xl border border-border bg-card">
          {recentAudit.length === 0 ? (
            <div className="p-5 text-sm text-muted-foreground">
              No audit entries yet.
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-4 py-2">When</th>
                  <th className="px-4 py-2">Action</th>
                  <th className="px-4 py-2">Actor</th>
                </tr>
              </thead>
              <tbody>
                {recentAudit.map((a) => (
                  <tr key={a.id} className="border-t border-border">
                    <td className="px-4 py-2 text-muted-foreground">
                      {new Date(a.at).toLocaleString()}
                    </td>
                    <td className="px-4 py-2 font-mono text-xs">{a.action}</td>
                    <td className="px-4 py-2 font-mono text-xs text-muted-foreground">
                      {a.actor_user_id ? a.actor_user_id.slice(0, 8) + "…" : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>
    </div>
  );
}
