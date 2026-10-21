"use client";

/**
 * /agent-chat — the user's chat thread with their booking agent.
 *
 * T8e-booking-agent (2026-07-24).
 *
 * Visible only to concierge-tier users. Two-column layout:
 *   - Left: list of the user's itineraries
 *   - Right: thread view (polled every 3s) + post box + attachments
 *
 * Threads are 1:1 between user and agent; users can post messages and
 * upload attachments (passport scans, visa copies), and read the agent's
 * responses. The agent's booking summary (is_summary=True) renders as
 * a styled card at the top of the thread.
 */

import { useEffect, useRef, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { apiFetch, ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth-context";

type ItinerarySummary = {
  id: string;
  title: string;
  starts_at: string;
  ends_at: string;
  destination_name?: string | null;
};

type AttachmentOut = {
  id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  kind?: string | null;
  download_url: string;
};

type MessageOut = {
  id: string;
  itinerary_id: string;
  sender_role: "user" | "agent" | "system";
  body: string;
  is_summary: boolean;
  booking_id?: string | null;
  created_at: string;
  attachments: AttachmentOut[];
};

type MessageList = {
  itinerary_id: string;
  total: number;
  items: MessageOut[];
};

const POLL_MS = 3000;

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function attachmentIcon(mime: string): string {
  if (mime.startsWith("image/")) return "🖼";
  if (mime === "application/pdf") return "📄";
  return "📎";
}

export default function AgentChatPage() {
  const router = useRouter();
  const { user, ready } = useAuth();
  const [itineraries, setItineraries] = useState<ItinerarySummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [messages, setMessages] = useState<MessageOut[]>([]);
  const [posting, setPosting] = useState(false);
  const [body, setBody] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [uploadingFor, setUploadingFor] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // Tier guard: redirect free/limited/unlimited to /itineraries
  useEffect(() => {
    if (!ready) return;
    if (!user) return; // auth-context will redirect to /auth
    if (user.tier !== "concierge") {
      router.push("/itineraries");
    }
  }, [ready, user, router]);

  // Load the user's itineraries
  useEffect(() => {
    if (!ready || !user || user.tier !== "concierge") return;
    (async () => {
      try {
        // The saved list lives at GET /api/itineraries (total+items).
        const res = await apiFetch<{ items: ItinerarySummary[] }>(
          "/api/itineraries",
        );
        setItineraries(res.items ?? []);
        if (res.items?.length && !selected) {
          // Deep link: /agent-chat?select=<id> (from a saved trip's
          // "Message your agent" button) wins over the first item.
          const fromUrl = new URLSearchParams(window.location.search).get("select");
          if (fromUrl && res.items.some((x) => x.id === fromUrl)) {
            setSelected(fromUrl);
          } else {
            setSelected(res.items[0].id);
          }
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load trips");
      }
    })();
  }, [ready, user, selected]);

  // Poll messages for the selected itinerary
  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    let lastSeen: string | null = null;

    const tick = async () => {
      try {
        const url = lastSeen
          ? `/api/messages?itinerary_id=${selected}&since=${encodeURIComponent(lastSeen)}`
          : `/api/messages?itinerary_id=${selected}`;
        const res = await apiFetch<MessageList>(url);
        if (cancelled) return;
        if (!lastSeen) {
          setMessages(res.items);
        } else if (res.items.length) {
          setMessages((prev) => [...prev, ...res.items]);
        }
        if (res.items.length) {
          lastSeen = res.items[res.items.length - 1].created_at;
        }
        setError(null);
      } catch (e) {
        if (e instanceof ApiError && e.status === 403) {
          router.push("/itineraries");
          return;
        }
        setError(e instanceof Error ? e.message : "Failed to load messages");
      }
    };

    tick();
    const interval = setInterval(tick, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [selected, router]);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const handlePost = useCallback(async () => {
    if (!selected || !body.trim()) return;
    setPosting(true);
    setError(null);
    try {
      const res = await apiFetch<MessageOut>("/api/messages", {
        method: "POST",
        body: { itinerary_id: selected, body: body.trim() },
      });
      setMessages((prev) => [...prev, res]);
      setBody("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to send message");
    } finally {
      setPosting(false);
    }
  }, [selected, body]);

  const handleUploadClick = useCallback((messageId: string) => {
    setUploadingFor(messageId);
    fileInputRef.current?.click();
  }, []);

  const handleFileChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      e.target.value = ""; // reset so the same file can be picked twice
      if (!file || !uploadingFor) return;
      setError(null);
      try {
        const fd = new FormData();
        fd.append("message_id", uploadingFor);
        fd.append("file", file);
        const kind = file.name.toLowerCase().includes("passport")
          ? "passport_scan"
          : file.name.toLowerCase().includes("visa")
            ? "visa_copy"
            : "other";
        fd.append("kind", kind);
        await apiFetch<AttachmentOut>("/api/messages/attachments", {
          method: "POST",
          body: fd,
          headers: {}, // let the browser set Content-Type for multipart
        });
        // Re-fetch the thread so the new attachment appears
        const res = await apiFetch<MessageList>(
          `/api/messages?itinerary_id=${selected}`,
        );
        setMessages(res.items);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Upload failed");
      } finally {
        setUploadingFor(null);
      }
    },
    [uploadingFor, selected],
  );

  if (!ready) {
    return <p className="p-8 text-muted-foreground">Loading…</p>;
  }
  if (!user || user.tier !== "concierge") {
    return <p className="p-8 text-muted-foreground">Redirecting…</p>;
  }

  const selectedItin = itineraries.find((i) => i.id === selected);

  return (
    <main className="container max-w-6xl py-8">
      <div className="mb-4 flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold">Your booking agent</h1>
        <Link href="/saved" className="text-sm text-muted-foreground underline">
          ← back to saved trips
        </Link>
      </div>

      {error && (
        <div className="mb-3 rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          {error}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-[280px_1fr]">
        {/* Sidebar: list of itineraries */}
        <aside className="rounded-lg border border-border bg-card p-3">
          <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            Your trips
          </h2>
          {itineraries.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              No saved trips yet.{" "}
              <Link href="/itineraries" className="underline">
                Find one →
              </Link>
            </p>
          ) : (
            <ul className="space-y-1">
              {itineraries.map((it) => (
                <li key={it.id}>
                  <button
                    onClick={() => setSelected(it.id)}
                    className={`w-full rounded-md px-2 py-2 text-left text-sm transition ${
                      selected === it.id
                        ? "bg-primary/15 text-foreground"
                        : "hover:bg-muted"
                    }`}
                  >
                    <div className="font-medium">{it.title}</div>
                    <div className="text-xs text-muted-foreground">
                      {it.destination_name ?? "—"} ·{" "}
                      {fmtTime(it.starts_at).split(",")[0]}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </aside>

        {/* Right pane: thread view */}
        <section className="rounded-lg border border-border bg-card">
          {selectedItin ? (
            <>
              <header className="border-b border-border px-4 py-3">
                <h2 className="font-semibold">{selectedItin.title}</h2>
                <p className="text-xs text-muted-foreground">
                  {selectedItin.destination_name ?? "—"} ·{" "}
                  {fmtTime(selectedItin.starts_at)} →{" "}
                  {fmtTime(selectedItin.ends_at)}
                </p>
              </header>

              {/* Thread scroll area */}
              <div
                ref={scrollRef}
                className="max-h-[55vh] overflow-y-auto px-4 py-3 space-y-3"
              >
                {messages.length === 0 ? (
                  <p className="text-sm text-muted-foreground">
                    No messages yet. Send the first one below.
                  </p>
                ) : (
                  messages.map((m) => (
                    <MessageBubble
                      key={m.id}
                      message={m}
                      onUploadClick={handleUploadClick}
                    />
                  ))
                )}
              </div>

              {/* Post box */}
              <footer className="border-t border-border p-3">
                <div className="flex gap-2">
                  <textarea
                    rows={2}
                    value={body}
                    onChange={(e) => setBody(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                        handlePost();
                      }
                    }}
                    placeholder="Type a message… (⌘+Enter to send)"
                    className="flex-1 resize-none rounded-md border border-border bg-background px-3 py-2 text-sm"
                  />
                  <button
                    onClick={handlePost}
                    disabled={posting || !body.trim()}
                    className="rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50"
                  >
                    {posting ? "Sending…" : "Send"}
                  </button>
                </div>
                <input
                  ref={fileInputRef}
                  type="file"
                  className="hidden"
                  accept="image/png,image/jpeg,image/webp,application/pdf,text/plain"
                  onChange={handleFileChange}
                />
              </footer>
            </>
          ) : (
            <p className="p-6 text-sm text-muted-foreground">
              Select a trip from the left to see the conversation.
            </p>
          )}
        </section>
      </div>
    </main>
  );
}

function MessageBubble({
  message,
  onUploadClick,
}: {
  message: MessageOut;
  onUploadClick: (messageId: string) => void;
}) {
  const isAgent = message.sender_role === "agent";
  const isSystem = message.sender_role === "system";
  const isMe = message.sender_role === "user";

  if (message.is_summary) {
    // Booking summary card — the agent posts this on confirm; user reads it
    return (
      <article className="rounded-lg border border-amber-400/40 bg-gradient-to-br from-amber-500/10 to-rose-500/10 p-4">
        <header className="mb-2 flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wide text-amber-300">
            📋 Booking summary
          </span>
          <span className="text-xs text-muted-foreground">
            {fmtTime(message.created_at)}
          </span>
        </header>
        <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">
          {message.body}
        </pre>
        {message.attachments.length > 0 && (
          <AttachmentList attachments={message.attachments} />
        )}
      </article>
    );
  }

  return (
    <div className={`flex ${isMe ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-2 text-sm shadow-sm ${
          isAgent
            ? "bg-amber-500/15 border border-amber-400/30"
            : isSystem
              ? "bg-muted text-muted-foreground italic"
              : "bg-primary/15 border border-primary/30"
        }`}
      >
        <div className="mb-1 flex items-center justify-between gap-3 text-[10px] uppercase tracking-wide">
          <span className="font-semibold opacity-80">
            {isMe ? "You" : isAgent ? "Agent" : "System"}
          </span>
          <span className="opacity-60">{fmtTime(message.created_at)}</span>
        </div>
        <p className="whitespace-pre-wrap">{message.body}</p>
        {message.attachments.length > 0 && (
          <AttachmentList attachments={message.attachments} />
        )}
        {isMe && (
          <div className="mt-2">
            <button
              onClick={() => onUploadClick(message.id)}
              className="text-[10px] text-muted-foreground underline"
            >
              + attach file
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

function AttachmentList({ attachments }: { attachments: AttachmentOut[] }) {
  return (
    <ul className="mt-2 space-y-1 border-t border-border/40 pt-2">
      {attachments.map((a) => (
        <li key={a.id}>
          <a
            href={`http://localhost:8000${a.download_url}`}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 text-xs underline"
          >
            <span>{attachmentIcon(a.mime_type)}</span>
            <span className="truncate">{a.filename}</span>
            <span className="text-muted-foreground">{fmtBytes(a.size_bytes)}</span>
          </a>
        </li>
      ))}
    </ul>
  );
}