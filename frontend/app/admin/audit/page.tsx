"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { apiFetch, ApiError } from "../../../lib/api";

type AuditItem = {
  id: string;
  actor_user_id: string | null;
  actor_kind: string;
  action: string;
  target_kind: string | null;
  target_id: string | null;
  metadata: Record<string, unknown>;
  request_id: string | null;
  at: string;
};

const ACTION_OPTIONS = [
  "user.register",
  "user.intake_updated",
  "user.grant_role",
  "user.revoke_role",
  "user.update",
  "source.toggle",
  "weights.update",
  "itineraries.discover",
  "itineraries.save",
  "agent.queue.requested",
  "agent.queue.claimed",
  "agent.queue.outcome",
];

const PAGE_SIZE = 50;

export default function AdminAuditPage() {
  const router = useRouter();
  const params = useSearchParams();
  const [items, setItems] = useState<AuditItem[] | null>(null);
  const [total, setTotal] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [action, setAction] = useState<string>(params.get("action") ?? "");
  const [actorId, setActorId] = useState<string>(params.get("actor_user_id") ?? "");
  const [offset, setOffset] = useState<number>(Number(params.get("offset") ?? 0));
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    try {
      const sp = new URLSearchParams();
      if (action) sp.set("action", action);
      if (actorId) sp.set("actor_user_id", actorId);
      sp.set("limit", String(PAGE_SIZE));
      sp.set("offset", String(offset));
      const data = await apiFetch<{
        total: number;
        items: AuditItem[];
      }>(`/api/admin/audit?${sp.toString()}`);
      setItems(data.items);
      setTotal(data.total);
      setErr(null);
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Failed to load audit (${e.status})`
          : e instanceof Error
            ? e.message
            : "Failed to load audit"
      );
    }
  }, [action, actorId, offset]);

  useEffect(() => {
    load();
  }, [load]);

  const applyFilters = () => {
    setOffset(0);
    const sp = new URLSearchParams();
    if (action) sp.set("action", action);
    if (actorId) sp.set("actor_user_id", actorId);
    router.replace(`/admin/audit?${sp.toString()}`);
  };

  const toggleExpand = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold">Audit log</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {total.toLocaleString()} matching entries (newest first)
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-3 rounded-xl border border-border bg-card p-4">
        <label className="flex flex-col text-xs text-muted-foreground">
          Action
          <select
            value={action}
            onChange={(e) => setAction(e.target.value)}
            className="mt-1 rounded border border-border bg-background px-2 py-1 text-sm"
          >
            <option value="">All</option>
            {ACTION_OPTIONS.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col text-xs text-muted-foreground">
          Actor user ID
          <input
            value={actorId}
            onChange={(e) => setActorId(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && applyFilters()}
            placeholder="UUID"
            className="mt-1 w-72 rounded border border-border bg-background px-2 py-1 font-mono text-xs"
          />
        </label>
        <button
          onClick={applyFilters}
          className="rounded bg-foreground/10 px-3 py-1.5 text-sm font-medium transition hover:bg-foreground/20"
        >
          Apply
        </button>
        {(action || actorId) && (
          <button
            onClick={() => {
              setAction("");
              setActorId("");
              setOffset(0);
              router.replace("/admin/audit");
            }}
            className="rounded border border-border bg-background px-3 py-1.5 text-sm transition hover:bg-muted"
          >
            Clear
          </button>
        )}
      </div>

      {err && (
        <div className="rounded-lg border border-rose-300 bg-rose-50 p-3 text-sm text-rose-900 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-200">
          {err}
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-border bg-card">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="w-10 px-2 py-2"></th>
              <th className="px-4 py-2">When</th>
              <th className="px-4 py-2">Action</th>
              <th className="px-4 py-2">Actor</th>
              <th className="px-4 py-2">Target</th>
            </tr>
          </thead>
          <tbody>
            {items === null ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">
                  Loading…
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">
                  No entries match the current filters.
                </td>
              </tr>
            ) : (
              items.map((a) => {
                const isOpen = expanded.has(a.id);
                return (
                  <Fragment key={a.id}>
                    <tr
                      className="cursor-pointer border-t border-border align-top transition hover:bg-muted/30"
                      onClick={() => toggleExpand(a.id)}
                    >
                      <td className="px-2 py-2 text-center text-muted-foreground">
                        {isOpen ? "▾" : "▸"}
                      </td>
                      <td className="whitespace-nowrap px-4 py-2 text-xs text-muted-foreground">
                        {new Date(a.at).toLocaleString()}
                      </td>
                      <td className="px-4 py-2 font-mono text-xs">{a.action}</td>
                      <td className="px-4 py-2 font-mono text-xs text-muted-foreground">
                        {a.actor_kind}:{a.actor_user_id ? a.actor_user_id.slice(0, 8) + "…" : "—"}
                      </td>
                      <td className="px-4 py-2 font-mono text-xs text-muted-foreground">
                        {a.target_kind ? `${a.target_kind}:${a.target_id?.slice(0, 8) ?? "—"}` : "—"}
                      </td>
                    </tr>
                    {isOpen && (
                      <tr className="border-t border-border bg-muted/20">
                        <td colSpan={5} className="px-4 py-3">
                          <div className="text-xs text-muted-foreground">Metadata</div>
                          <pre className="mt-1 overflow-x-auto rounded bg-background p-2 font-mono text-[11px]">
                            {JSON.stringify(a.metadata, null, 2)}
                          </pre>
                          {a.request_id && (
                            <div className="mt-2 text-xs text-muted-foreground">
                              request_id: <code>{a.request_id}</code>
                            </div>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between text-sm">
          <span className="text-muted-foreground">
            Showing {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
          </span>
          <div className="flex gap-2">
            <button
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              className="rounded border border-border bg-card px-3 py-1 disabled:opacity-50"
            >
              ← Previous
            </button>
            <button
              disabled={offset + PAGE_SIZE >= total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
              className="rounded border border-border bg-card px-3 py-1 disabled:opacity-50"
            >
              Next →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
