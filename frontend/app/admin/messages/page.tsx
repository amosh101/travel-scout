"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { apiFetch, ApiError } from "../../../lib/api";
import { useAuth } from "../../../lib/auth-context";

/**
 * Chat console (admin/agent surface).
 *
 * - Index  : every chat thread, most recently active first (agent.work
 *            | agent.assign | itinerary.read_all — the backend enforces).
 * - Thread : full history + reply box. Agents REPLY; supervisory admins
 *            (itinerary.read_all, no agent.work, not concierge) read
 *            only — the composer is hidden server-side too.
 */

type ThreadSummary = {
  itinerary_id: string;
  itinerary_title: string | null;
  owner_id: string;
  owner_email: string;
  owner_name: string;
  message_count: number;
  first_at: string | null;
  last_at: string | null;
  last_body: string | null;
  last_sender_role: string | null;
  last_is_summary: boolean;
  queue_status: string | null;
};

type AttachmentOut = {
  id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  download_url: string;
};

type MessageOut = {
  id: string;
  itinerary_id: string;
  sender_user_id: string;
  sender_role: string;
  body: string;
  is_summary: boolean;
  created_at: string;
  attachments: AttachmentOut[];
};

export default function AdminMessagesPage() {
  const { user, userReady } = useAuth();
  const sp = useSearchParams();
  const current = sp.get("it");

  const [threads, setThreads] = useState<ThreadSummary[] | null>(null);
  const [threadsErr, setThreadsErr] = useState<string | null>(null);

  const loadThreads = useCallback(async () => {
    try {
      const data = await apiFetch<{ total: number; items: ThreadSummary[] }>(
        "/api/messages/threads?limit=100",
      );
      setThreads(data.items);
      setThreadsErr(null);
    } catch (e) {
      setThreadsErr(
        e instanceof ApiError
          ? `Failed to load threads (${e.status})`
          : e instanceof Error
            ? e.message
            : "Failed to load threads",
      );
    }
  }, []);

  useEffect(() => {
    loadThreads();
    // The inbox moves — poll lightly.
    const t = setInterval(loadThreads, 20000);
    return () => clearInterval(t);
  }, [loadThreads]);

  if (!userReady) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }

  if (current) {
    return <ThreadView itineraryId={current} isAgentSurface onDone={loadThreads} />;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold">Customer conversations</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Every thread a customer or agent has posted in, most recently
          active first. Open one to read the full history
          {canWrite(user) ? " and reply" : " (read-only for your role)"}.
        </p>
      </div>

      {threadsErr && (
        <div className="rounded-lg border border-rose-300 bg-rose-50 p-3 text-sm text-rose-900 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-200">
          {threadsErr}
        </div>
      )}

      {threads === null ? (
        <div className="h-16 animate-pulse rounded-xl border border-border bg-card" />
      ) : threads.length === 0 ? (
        <div className="rounded-xl border border-border bg-card p-8 text-center text-muted-foreground">
          No conversations yet. Threads open when a customer with a concierge
          plan messages about a trip, or when a hand-off is worked in chat.
        </div>
      ) : (
        <div className="space-y-3">
          {threads.map((t) => (
            <Link
              key={t.itinerary_id}
              href={`/admin/messages?it=${t.itinerary_id}`}
              className="block rounded-xl border border-border bg-card p-4 transition hover:border-foreground/30"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">
                      {t.itinerary_title || "Untitled trip"}
                    </span>
                    {t.queue_status && <QueueChip status={t.queue_status} />}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {t.owner_name} · {t.owner_email}
                  </div>
                </div>
                <div className="text-xs text-muted-foreground">
                  {t.message_count} message{t.message_count === 1 ? "" : "s"}
                  {t.last_at && (
                    <> · {new Date(t.last_at).toLocaleString()}</>
                  )}
                </div>
              </div>
              {t.last_body && (
                <div className="mt-2 truncate text-sm text-muted-foreground">
                <span className="font-medium text-foreground">
                  {t.last_sender_role === "agent" ? "Agent:" : t.last_sender_role === "user" ? "Customer:" : ""}
                </span>{" "}
                {t.last_body}
                {t.last_is_summary && " (booking summary)"}
                </div>
              )}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function QueueChip({ status }: { status: string }) {
  const cls =
    status === "pending"
      ? "bg-amber-100 text-amber-900 dark:bg-amber-900/40 dark:text-amber-200"
      : status === "claimed" || status === "in_progress"
        ? "bg-sky-100 text-sky-900 dark:bg-sky-900/40 dark:text-sky-200"
        : status === "confirmed"
          ? "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-200"
          : status === "failed"
            ? "bg-rose-100 text-rose-900 dark:bg-rose-950/40 dark:text-rose-200"
            : "bg-muted text-muted-foreground";
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs ${cls}`}>
      hand-off: {status}
    </span>
  );
}

function canWrite(
  user: { tier: string; permissions: string[] } | null,
): boolean {
  if (!user) return false;
  return user.tier === "concierge" || user.permissions.includes("agent.work");
}

// ---------------------------------------------------------------------------

function ThreadView({
  itineraryId,
  isAgentSurface,
  onDone,
}: {
  itineraryId: string;
  isAgentSurface: boolean;
  onDone?: () => void;
}) {
  const { user, userReady } = useAuth();
  const [items, setItems] = useState<MessageOut[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);

  // Booking-summary composer state (agent convenience).
  const [showSummary, setShowSummary] = useState(false);
  const [sumStart, setSumStart] = useState("");
  const [sumEnd, setSumEnd] = useState("");
  const [sumDest, setSumDest] = useState("");
  const [sumPassport, setSumPassport] = useState("");
  const [sumVisaReq, setSumVisaReq] = useState("");
  const [sumVisaStatus, setSumVisaStatus] = useState("");
  const [sumNotes, setSumNotes] = useState("");

  const load = useCallback(async () => {
    try {
      const data = await apiFetch<{
        total: number;
        items: MessageOut[];
      }>(`/api/messages?itinerary_id=${itineraryId}&limit=500`);
      setItems(data.items);
      setErr(null);
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Failed to load thread (${e.status})`
          : e instanceof Error
            ? e.message
            : "Failed to load thread",
      );
    }
  }, [itineraryId]);

  useEffect(() => {
    load();
    // Threads update while a customer is typing — poll lightly.
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, [load]);

  const writable = canWrite(user);

  const send = async () => {
    if (!body.trim()) return;
    setBusy(true);
    try {
      const payload: Record<string, unknown> = {
        itinerary_id: itineraryId,
        body: body.trim(),
      };
      if (showSummary) {
        payload.is_summary = true;
        if (sumStart) payload.summary_start_date = sumStart;
        if (sumEnd) payload.summary_end_date = sumEnd;
        if (sumDest) payload.summary_destination = sumDest;
        if (sumPassport) payload.summary_passport_required = sumPassport === "yes";
        if (sumVisaReq) payload.summary_visa_required = sumVisaReq === "yes";
        if (sumVisaStatus) payload.summary_visa_status = sumVisaStatus;
        if (sumNotes) payload.summary_notes = sumNotes;
      }
      const created = await apiFetch<MessageOut>("/api/messages", {
        method: "POST",
        body: payload,
      });
      if (created) {
        setBody("");
        setShowSummary(false);
        setSumStart("");
        setSumEnd("");
        setSumDest("");
        setSumPassport("");
        setSumVisaReq("");
        setSumVisaStatus("");
        setSumNotes("");
      }
      await load();
      onDone?.();
    } catch (e) {
      setErr(
        e instanceof ApiError ? `${e.status}: ${e.message}` : e instanceof Error ? e.message : "Send failed",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <Link
          href={isAgentSurface ? "/admin/messages" : "/admin/messages"}
          className="text-sm text-muted-foreground hover:underline"
        >
          ← all conversations
        </Link>
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

      {items === null ? (
        <div className="space-y-2">
          <div className="h-10 animate-pulse rounded-xl border border-border bg-card" />
          <div className="h-10 w-2/3 animate-pulse rounded-xl border border-border bg-card" />
        </div>
      ) : items.length === 0 ? (
        <div className="rounded-xl border border-border bg-card p-8 text-center text-muted-foreground">
          No messages in this thread yet.
        </div>
      ) : (
        <div className="space-y-3">
          {items.map((m) => (
            <Bubble key={m.id} m={m} />
          ))}
        </div>
      )}

      {items !== null && items.length > 0 && (
        <SummaryCard items={items} />
      )}

      {writable ? (
        <div className="rounded-xl border border-border bg-card p-4">
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="Reply to the customer…"
            rows={3}
            className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
          />
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <button
              onClick={send}
              disabled={busy || !body.trim()}
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
            >
              {busy ? "Sending…" : "Send reply"}
            </button>
            <label className="flex items-center gap-2 text-sm text-muted-foreground">
              <input
                type="checkbox"
                checked={showSummary}
                onChange={(e) => setShowSummary(e.target.checked)}
              />
              Include structured booking summary in this reply
            </label>
          </div>
          {showSummary && (
            <div className="mt-3 grid gap-3 border-t border-border pt-3 md:grid-cols-3">
              <label className="flex flex-col text-xs text-muted-foreground">
                Confirmed start date
                <input
                  type="date"
                  value={sumStart}
                  onChange={(e) => setSumStart(e.target.value)}
                  className="mt-1 rounded border border-border bg-background px-2 py-1 text-sm"
                />
              </label>
              <label className="flex flex-col text-xs text-muted-foreground">
                Confirmed end date
                <input
                  type="date"
                  value={sumEnd}
                  onChange={(e) => setSumEnd(e.target.value)}
                  className="mt-1 rounded border border-border bg-background px-2 py-1 text-sm"
                />
              </label>
              <label className="flex flex-col text-xs text-muted-foreground">
                Destination
                <input
                  value={sumDest}
                  onChange={(e) => setSumDest(e.target.value)}
                  className="mt-1 rounded border border-border bg-background px-2 py-1 text-sm"
                />
              </label>
              <label className="flex flex-col text-xs text-muted-foreground">
                Passport required?
                <select
                  value={sumPassport}
                  onChange={(e) => setSumPassport(e.target.value)}
                  className="mt-1 rounded border border-border bg-background px-2 py-1 text-sm"
                >
                  <option value="">—</option>
                  <option value="yes">yes</option>
                  <option value="no">no</option>
                </select>
              </label>
              <label className="flex flex-col text-xs text-muted-foreground">
                Visa required?
                <select
                  value={sumVisaReq}
                  onChange={(e) => setSumVisaReq(e.target.value)}
                  className="mt-1 rounded border border-border bg-background px-2 py-1 text-sm"
                >
                  <option value="">—</option>
                  <option value="yes">yes</option>
                  <option value="no">no</option>
                </select>
              </label>
              <label className="flex flex-col text-xs text-muted-foreground">
                Visa status
                <input
                  value={sumVisaStatus}
                  onChange={(e) => setSumVisaStatus(e.target.value)}
                  placeholder="e.g. e-visa on arrival"
                  className="mt-1 rounded border border-border bg-background px-2 py-1 text-sm"
                />
              </label>
              <label className="flex flex-col text-xs text-muted-foreground md:col-span-3">
                Notes for the summary card
                <input
                  value={sumNotes}
                  onChange={(e) => setSumNotes(e.target.value)}
                  className="mt-1 rounded border border-border bg-background px-2 py-1 text-sm"
                />
              </label>
            </div>
          )}
        </div>
      ) : (
        <div className="rounded-xl border border-amber-400/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/5 dark:text-amber-200">
          Supervisory view — you can read the history; replies are left to
          the booking agents.
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

function Bubble({ m }: { m: MessageOut }) {
  const summary = m.is_summary ? SummaryInline({ m }) : null;
  return (
    <div
      className={`max-w-2xl rounded-xl px-4 py-3 text-sm ${
        m.sender_role === "agent"
          ? "ml-auto bg-primary/10"
          : "mr-auto bg-card"
      } border border-border`}
    >
      <div className="mb-1 flex items-center gap-2 text-xs text-muted-foreground">
        <span
          className={`rounded-full px-2 py-0.5 ${
            m.sender_role === "agent"
              ? "bg-emerald-100 text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-200"
              : "bg-sky-100 text-sky-900 dark:bg-sky-900/40 dark:text-sky-200"
          }`}
        >
          {m.sender_role}
        </span>
        <span>{new Date(m.created_at).toLocaleString()}</span>
      </div>
      <div className="whitespace-pre-wrap text-foreground">{m.body}</div>
      {summary}
      {m.attachments.length > 0 && (
        <div className="mt-2 space-y-1">
          {m.attachments.map((a) => (
            <a
              key={a.id}
              href={a.download_url}
              className="block text-xs underline"
            >
              📎 {a.filename} ({Math.round(a.size_bytes / 102.4) / 10} kB)
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

function SummaryInline({ m }: { m: MessageOut }) {
  // The structured fields ride in the audit metadata; the message body
  // already carries the human view. Mark the card visibly.
  return (
    <div className="mt-2 rounded-lg border border-emerald-400/40 bg-emerald-500/10 px-3 py-2 text-xs font-medium text-emerald-900 dark:border-emerald-500/30 dark:bg-emerald-500/5 dark:text-emerald-200">
      Booking summary card
    </div>
  );
}

function SummaryCard({ items }: { items: MessageOut[] }) {
  const last = [...items].reverse().find((x) => x.is_summary);
  if (!last) return null;
  return (
    <div className="rounded-xl border border-emerald-400/40 bg-emerald-500/10 p-4 text-sm text-foreground dark:border-emerald-500/30 dark:bg-emerald-500/5">
      <div className="text-xs font-medium uppercase tracking-wide text-emerald-800 dark:text-emerald-300">
        Latest booking summary in thread
      </div>
      <div className="mt-1 whitespace-pre-wrap">{last.body}</div>
    </div>
  );
}