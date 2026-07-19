"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, ApiError } from "../../../lib/api";

type QueueItem = {
  id: string;
  user_id: string;
  user_email: string;
  user_name: string;
  itinerary_id: string | null;
  itinerary_title: string | null;
  itinerary_starts_at: string | null;
  itinerary_ends_at: string | null;
  itinerary_destination: string | null;
  status: string;
  amount_cents: number;
  currency: string;
  external_id: string | null;
  metadata: Record<string, unknown>;
  assigned_agent_id: string | null;
  claimed_at: string | null;
  outcome_at: string | null;
  outcome_note: string | null;
  created_at: string;
};

const STATUS_OPTIONS = ["", "pending", "claimed", "in_progress", "confirmed", "failed"];

function formatAmount(cents: number, currency: string) {
  if (!cents) return "—";
  return `${(cents / 100).toFixed(2)} ${currency}`;
}

export default function AdminQueuePage() {
  const [items, setItems] = useState<QueueItem[]>([]);
  const [total, setTotal] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("");
  const [busy, setBusy] = useState<string | null>(null);
  const [outcomeDrafts, setOutcomeDrafts] = useState<Record<string, {
    status: string; amount: string; currency: string; external_id: string; note: string;
  }>>({});

  const load = useCallback(async () => {
    try {
      const sp = new URLSearchParams();
      if (status) sp.set("status", status);
      sp.set("limit", "100");
      const data = await apiFetch<{ total: number; items: QueueItem[] }>(
        `/api/agent/queue?${sp.toString()}`
      );
      setItems(data.items);
      setTotal(data.total);
      setErr(null);
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Failed to load queue (${e.status})`
          : e instanceof Error
            ? e.message
            : "Failed to load queue"
      );
    }
  }, [status]);

  useEffect(() => {
    load();
  }, [load]);

  const claim = async (id: string) => {
    setBusy(id);
    try {
      await apiFetch(`/api/agent/queue/${id}/claim`, { method: "POST" });
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Claim failed");
    } finally {
      setBusy(null);
    }
  };

  const release = async (id: string) => {
    setBusy(id);
    try {
      await apiFetch(`/api/agent/queue/${id}/release`, { method: "POST", body: {} });
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Release failed");
    } finally {
      setBusy(null);
    }
  };

  const recordOutcome = async (id: string) => {
    const draft = outcomeDrafts[id];
    if (!draft) return;
    if (draft.status !== "confirmed" && draft.status !== "failed") return;
    setBusy(id);
    try {
      const body: Record<string, unknown> = { status: draft.status };
      if (draft.amount) body.amount_cents = Math.round(parseFloat(draft.amount) * 100);
      if (draft.currency) body.currency = draft.currency.toUpperCase();
      if (draft.external_id) body.external_id = draft.external_id;
      if (draft.note) body.note = draft.note;
      await apiFetch(`/api/agent/queue/${id}/outcome`, { method: "POST", body });
      setOutcomeDrafts((p) => {
        const n = { ...p };
        delete n[id];
        return n;
      });
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Outcome failed");
    } finally {
      setBusy(null);
    }
  };

  const ensureDraft = (id: string) => {
    if (!outcomeDrafts[id]) {
      setOutcomeDrafts((p) => ({
        ...p,
        [id]: { status: "confirmed", amount: "", currency: "USD", external_id: "", note: "" },
      }));
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold">Booking agent queue</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {total} item(s). When you call <code>claim</code>, the row is locked
          to your account. Call <code>outcome</code> when you finish the booking
          (confirmed or failed) with the price and any external reference.
        </p>
      </div>

      <div className="flex items-end gap-3 rounded-xl border border-border bg-card p-4">
        <label className="flex flex-col text-xs text-muted-foreground">
          Status
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            className="mt-1 rounded border border-border bg-background px-2 py-1 text-sm"
          >
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s || "All (my queue + unclaimed)"}
              </option>
            ))}
          </select>
        </label>
        <button
          onClick={load}
          className="rounded bg-foreground/10 px-3 py-1.5 text-sm font-medium transition hover:bg-foreground/20"
        >
          Refresh
        </button>
      </div>

      {err && (
        <div className="rounded-lg border border-rose-300 bg-rose-50 p-3 text-sm text-rose-900 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-200">
          {err}
        </div>
      )}

      {items.length === 0 ? (
        <div className="rounded-xl border border-border bg-card p-8 text-center text-muted-foreground">
          No items in the queue.
        </div>
      ) : (
        <div className="space-y-3">
          {items.map((q) => {
            const isMine = q.assigned_agent_id !== null;
            const draft = outcomeDrafts[q.id];
            return (
              <div
                key={q.id}
                className="rounded-xl border border-border bg-card p-5"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span
                        className={`rounded-full px-2 py-0.5 text-xs ${
                          q.status === "pending"
                            ? "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200"
                            : q.status === "claimed" || q.status === "in_progress"
                              ? "bg-sky-100 text-sky-900 dark:bg-sky-900/40 dark:text-sky-200"
                              : q.status === "confirmed"
                                ? "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-200"
                                : q.status === "failed"
                                  ? "bg-rose-100 text-rose-900 dark:bg-rose-900/40 dark:text-rose-200"
                                  : "bg-muted"
                        }`}
                      >
                        {q.status}
                      </span>
                      {isMine && (
                        <span className="rounded-full bg-violet-100 px-2 py-0.5 text-xs text-violet-900 dark:bg-violet-900/40 dark:text-violet-200">
                          claimed by you
                        </span>
                      )}
                    </div>
                    <div className="mt-2 text-sm">
                      <div className="font-medium">{q.user_name}</div>
                      <div className="text-muted-foreground">{q.user_email}</div>
                    </div>
                    {q.itinerary_title && (
                      <div className="mt-2 text-sm">
                        <span className="text-muted-foreground">Itinerary: </span>
                        {q.itinerary_title}
                        {q.itinerary_starts_at && (
                          <span className="ml-1 text-muted-foreground">
                            ({q.itinerary_starts_at.slice(0, 10)}
                            {q.itinerary_ends_at ? ` → ${q.itinerary_ends_at.slice(0, 10)}` : ""})
                          </span>
                        )}
                      </div>
                    )}
                    <div className="mt-1 text-xs text-muted-foreground">
                      Handed off {new Date(q.created_at).toLocaleString()}
                      {q.claimed_at && (
                        <> · Claimed {new Date(q.claimed_at).toLocaleString()}</>
                      )}
                      {q.outcome_at && (
                        <> · Outcome {new Date(q.outcome_at).toLocaleString()}</>
                      )}
                    </div>
                    {(q.amount_cents > 0 || q.external_id || q.outcome_note) && (
                      <div className="mt-2 text-sm">
                        {q.amount_cents > 0 && (
                          <span className="mr-3">
                            <span className="text-muted-foreground">Amount: </span>
                            <span className="font-mono">
                              {formatAmount(q.amount_cents, q.currency)}
                            </span>
                          </span>
                        )}
                        {q.external_id && (
                          <span className="mr-3">
                            <span className="text-muted-foreground">External: </span>
                            <span className="font-mono text-xs">{q.external_id}</span>
                          </span>
                        )}
                      </div>
                    )}
                    {q.outcome_note && (
                      <div className="mt-2 text-sm text-muted-foreground">
                        Note: {q.outcome_note}
                      </div>
                    )}
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-2">
                    {q.status === "pending" && (
                      <button
                        onClick={() => claim(q.id)}
                        disabled={busy === q.id}
                        className="rounded bg-foreground/10 px-3 py-1 text-sm font-medium transition hover:bg-foreground/20 disabled:opacity-50"
                      >
                        {busy === q.id ? "…" : "Claim"}
                      </button>
                    )}
                    {(q.status === "claimed" || q.status === "in_progress") && isMine && (
                      <>
                        <button
                          onClick={() => ensureDraft(q.id)}
                          className="rounded bg-emerald-100 px-3 py-1 text-sm font-medium text-emerald-900 transition hover:bg-emerald-200 dark:bg-emerald-900/40 dark:text-emerald-200"
                        >
                          Record outcome
                        </button>
                        <button
                          onClick={() => release(q.id)}
                          disabled={busy === q.id}
                          className="rounded border border-border bg-background px-3 py-1 text-xs text-muted-foreground transition hover:bg-muted disabled:opacity-50"
                        >
                          Release
                        </button>
                      </>
                    )}
                    {(q.status === "claimed" || q.status === "in_progress") && !isMine && (
                      <span className="text-xs text-muted-foreground">
                        (claimed by another agent)
                      </span>
                    )}
                  </div>
                </div>

                {draft && (
                  <div className="mt-4 border-t border-border pt-4">
                    <div className="grid gap-3 md:grid-cols-5">
                      <label className="flex flex-col text-xs text-muted-foreground">
                        Status
                        <select
                          value={draft.status}
                          onChange={(e) =>
                            setOutcomeDrafts((p) => ({
                              ...p,
                              [q.id]: { ...p[q.id], status: e.target.value },
                            }))
                          }
                          className="mt-1 rounded border border-border bg-background px-2 py-1 text-sm"
                        >
                          <option value="confirmed">confirmed</option>
                          <option value="failed">failed</option>
                        </select>
                      </label>
                      <label className="flex flex-col text-xs text-muted-foreground">
                        Amount
                        <input
                          value={draft.amount}
                          onChange={(e) =>
                            setOutcomeDrafts((p) => ({
                              ...p,
                              [q.id]: { ...p[q.id], amount: e.target.value },
                            }))
                          }
                          placeholder="0.00"
                          className="mt-1 rounded border border-border bg-background px-2 py-1 text-sm"
                        />
                      </label>
                      <label className="flex flex-col text-xs text-muted-foreground">
                        Currency
                        <input
                          value={draft.currency}
                          onChange={(e) =>
                            setOutcomeDrafts((p) => ({
                              ...p,
                              [q.id]: { ...p[q.id], currency: e.target.value },
                            }))
                          }
                          maxLength={3}
                          className="mt-1 rounded border border-border bg-background px-2 py-1 text-sm uppercase"
                        />
                      </label>
                      <label className="flex flex-col text-xs text-muted-foreground md:col-span-2">
                        External ID
                        <input
                          value={draft.external_id}
                          onChange={(e) =>
                            setOutcomeDrafts((p) => ({
                              ...p,
                              [q.id]: { ...p[q.id], external_id: e.target.value },
                            }))
                          }
                          placeholder="e.g. F1-12345 or hotel confirmation"
                          className="mt-1 rounded border border-border bg-background px-2 py-1 text-sm"
                        />
                      </label>
                      <label className="flex flex-col text-xs text-muted-foreground md:col-span-5">
                        Note
                        <input
                          value={draft.note}
                          onChange={(e) =>
                            setOutcomeDrafts((p) => ({
                              ...p,
                              [q.id]: { ...p[q.id], note: e.target.value },
                            }))
                          }
                          placeholder="optional"
                          className="mt-1 rounded border border-border bg-background px-2 py-1 text-sm"
                        />
                      </label>
                    </div>
                    <div className="mt-3 flex justify-end gap-2">
                      <button
                        onClick={() =>
                          setOutcomeDrafts((p) => {
                            const n = { ...p };
                            delete n[q.id];
                            return n;
                          })
                        }
                        className="rounded border border-border bg-background px-3 py-1 text-sm transition hover:bg-muted"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={() => recordOutcome(q.id)}
                        disabled={busy === q.id}
                        className="rounded bg-foreground/10 px-3 py-1 text-sm font-medium transition hover:bg-foreground/20 disabled:opacity-50"
                      >
                        {busy === q.id ? "Saving…" : "Save outcome"}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
