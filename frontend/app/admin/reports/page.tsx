"use client";

/**
 * Reports — permission-driven per persona:
 * - report.read (admin/superadmin): Usage · Trips · Finance · Resources.
 * - agent.work (agents): my queue/report + my audit trail.
 * All data from the real reports endpoints; honest errors per section.
 */

import { useAuth } from "@/lib/auth-context";
import { useEffect, useState } from "react";

type Report = Record<string, unknown>;

function fmtCents(v: number | undefined | null): string {
  const n = typeof v === "number" ? v : 0;
  return (n / 100).toFixed(2);
}

function ErrorBox({ msg }: { msg: string }) {
  return (
    <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm text-foreground">
      {msg}
    </div>
  );
}

function Card({
  title, children,
}: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-border bg-card p-6">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
      </h2>
      <div className="mt-3">{children}</div>
    </section>
  );
}

function StatRows({ rows, headers }: { rows: string[][]; headers: string[] }) {
  if (rows.length === 0)
    return <p className="text-sm text-muted-foreground">Nothing recorded in this window.</p>;
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="text-left text-xs text-muted-foreground">
          {headers.map((h) => (
            <th key={h} className="pb-1 pr-3 font-medium">{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={i} className="border-t border-border/60">
            {r.map((c, j) => (
              <td key={j} className="py-1.5 pr-3 font-mono text-xs text-foreground">{c}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function AdminReportsPage() {
  const { token, ready, user } = useAuth();
  const isAdminReports = !!user?.permissions?.includes("report.read");
  const isAgent = !!user?.permissions?.includes("agent.work");

  const [days, setDays] = useState(30);
  const [usage, setUsage] = useState<Report | null>(null);
  const [trips, setTrips] = useState<Report | null>(null);
  const [finance, setFinance] = useState<Report | null>(null);
  const [resources, setResources] = useState<Report | null>(null);
  const [agentRep, setAgentRep] = useState<Report | null>(null);
  const [agentAudit, setAgentAudit] = useState<{ total: number; items: Record<string, unknown>[] } | null>(null);
  const [errs, setErrs] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!ready || !token) return;
    const base = process.env.NEXT_PUBLIC_API_URL;
    const hdr: RequestInit = { headers: { Authorization: `Bearer ${token}` } };
    const hits: Record<string, string> = {};

    const grab = (path: string, set: (d: Report) => void, key: string) =>
      fetch(base + path, hdr)
        .then(async (r) => {
          if (!r.ok) {
            const j = await r.json().catch(() => ({}));
            hits[key] = j.detail || `HTTP ${r.status}`;
            return;
          }
          set(await r.json());
        })
        .catch((e) => (hits[key] = e.message))
        .then(() => {
          setErrs({ ...hits });
        });

    if (isAdminReports) {
      grab(`/api/admin/reports/usage?days=${days}`, setUsage, "usage");
      grab(`/api/admin/reports/trips?days=${days}`, setTrips, "trips");
      grab(`/api/admin/reports/finance?days=${days}`, setFinance, "finance");
      grab(`/api/admin/reports/resources`, setResources, "resources");
    }
    if (isAgent) {
      grab(`/api/agent/reports/me?days=${days}`, setAgentRep, "agentRep");
      grab(`/api/agent/audit?limit=100`, (d) =>
        setAgentAudit(d as unknown as { total: number; items: Record<string, unknown>[] }),
        "agentAudit");
    }
  }, [ready, token, days, isAdminReports, isAgent]);

  if (!ready) return <p className="p-8 text-sm text-muted-foreground">Loading…</p>;

  const usageRows = usage
    ? Object.entries((usage.action_totals as Record<string, number>) || {})
        .map(([a, n]) => [a, String(n)])
    : [];
  const tripRows = trips
    ? Object.entries(((trips.handoffs as Record<string, unknown>)?.by_status as Record<string, number>) || {}).map(
        ([s, n]) => [s, String(n)],
      )
    : [];
  const financeRows = finance
    ? ((finance.agent_payments_by_currency as { currency: string; bookings: number; amount_cents: number; commission_cents: number }[]) || [])
        .map((p) => [p.currency, String(p.bookings), fmtCents(p.amount_cents), fmtCents(p.commission_cents)])
    : [];
  const subRows = finance
    ? ((finance.subscriptions as { tier: string; status: string; count: number }[]) || [])
        .map((s) => [s.tier, s.status, String(s.count)])
    : [];
  const resRows = resources
    ? [
        ["API CPU %", String((resources as Report).api_pid_cpu_pct ?? "—")],
        ["API RSS MB", String((((resources as Report).api_rss_bytes as number) / 1e6).toFixed(1))],
        ["Database MB", String((((resources as Report).database_bytes as number) / 1e6).toFixed(1))],
        ["Open queue items", String((resources as Report).open_queue_items ?? "—")],
        ["Digest scheduler", String((resources as Report).digest_scheduler_enabled ?? "—")],
      ]
    : [];
  const agentRows = agentRep
    ? Object.entries((agentRep.bookings_by_status as Record<string, { count: number; amount_cents: number; commission_cents: number }>) || {})
        .map(([s, v]) => [s, String(v.count), fmtCents(v.amount_cents), fmtCents(v.commission_cents)])
    : [];
  const myAuditRows = (agentAudit?.items || []).slice(0, 30).map((r) => [
    String(r.action),
    String(r.target_kind ?? ""),
    new Date(String(r.at)).toLocaleString(),
  ]);

  return (
    <div className="flex-1 p-8">
      <div className="mb-6 flex items-center gap-4">
        <h1 className="text-2xl font-semibold">Reports</h1>
        <select
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          className="rounded border border-border bg-card px-2 py-1 text-sm"
        >
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
          <option value={365}>Last 365 days</option>
        </select>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        {isAdminReports && (
          <>
            <Card title="App usage">
              {errs.usage ? <ErrorBox msg={`Usage: ${errs.usage}`} /> : (
                <>
                  <p className="text-sm text-muted-foreground">
                    {String(usage?.users_total ?? "—")} users ({String(usage?.users_active ?? "—")} active)
                    {" · "}
                    tiers: {usage ? Object.entries(usage.tier_distribution as Record<string, number> || {}).map(([t, n]) => `${t} ${n}`).join(", ") : "—"}
                  </p>
                  <div className="mt-4">
                    <StatRows rows={usageRows} headers={["Action", "Count"]} />
                  </div>
                </>
              )}
            </Card>
            <Card title="Trips">
              {errs.trips ? <ErrorBox msg={`Trips: ${errs.trips}`} /> : (
                <>
                  <p className="text-sm text-muted-foreground">
                    Saved all-time {String(trips?.itineraries_saved_total ?? 0)} · in window {String(trips?.itineraries_saved_in_window ?? 0)}
                    {" · confirmation rate "}
                    {trips ? String((trips.handoffs as Record<string, unknown>)?.confirmation_rate ?? "—") : "—"}
                  </p>
                  <div className="mt-4">
                    <StatRows rows={tripRows} headers={["Hand-off status", "Count"]} />
                  </div>
                </>
              )}
            </Card>
            <Card title="Financial">
              {errs.finance ? <ErrorBox msg={`Finance: ${errs.finance}`} /> : (
                <>
                  <StatRows rows={financeRows} headers={["Currency", "Bookings", "Paid", "Commission"]} />
                  <div className="mt-4">
                    <StatRows rows={subRows} headers={["Tier", "Status", "Count"]} />
                  </div>
                  {finance && Object.keys((finance.subscription_revenue_by_currency as Record<string, number>) || {}).length > 0 && (
                    <p className="mt-3 text-xs text-muted-foreground">
                      Subscription revenue: {Object.entries(finance.subscription_revenue_by_currency as Record<string, number>).map(([c, v]) => `${c} ${fmtCents(v)}`).join(", ")}
                    </p>
                  )}
                </>
              )}
            </Card>
            <Card title="App resources">
              {errs.resources ? <ErrorBox msg={`Resources: ${errs.resources}`} /> : (
                <StatRows rows={resRows} headers={["Metric", "Value"]} />
              )}
            </Card>
          </>
        )}

        {isAgent && (
          <>
            <Card title="My bookings">
              {errs.agentRep ? <ErrorBox msg={`My report: ${errs.agentRep}`} /> : (
                <>
                  <p className="text-sm text-muted-foreground">
                    Claimed all-time: {String((agentRep?.queue as Record<string, number> | undefined)?.claimed_by_me_total ?? 0)} · pending pool: {String((agentRep?.queue as Record<string, number> | undefined)?.pending_pool ?? 0)}
                  </p>
                  <div className="mt-4">
                    <StatRows rows={agentRows} headers={["Status", "Count", "Amount", "Commission"]} />
                  </div>
                </>
              )}
            </Card>
            <Card title="My audit trail">
              {errs.agentAudit ? <ErrorBox msg={`Audit: ${errs.agentAudit}`} /> : (
                <>
                  <p className="text-sm text-muted-foreground">
                    {String(agentAudit?.total ?? 0)} agent actions on record (latest 30 shown)
                  </p>
                  <div className="mt-4 max-h-96 overflow-auto">
                    <StatRows rows={myAuditRows} headers={["Action", "Target", "When"]} />
                  </div>
                </>
              )}
            </Card>
          </>
        )}
      </div>
    </div>
  );
}