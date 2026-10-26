"use client";

import { useAuth } from "@/lib/auth-context";
import { useEffect, useState } from "react";

const TIERS = [
  {
    key: "limited",
    name: "Limited",
    price: "$9/mo",
    blurb: "3 saved trips a month. Everything the engine finds, in your inbox weekly.",
  },
  {
    key: "unlimited",
    name: "Unlimited",
    price: "$24/mo",
    blurb: "Unlimited saved trips and searches. The full engine, no meter.",
  },
  {
    key: "concierge",
    name: "Concierge",
    price: "$59/mo",
    blurb: "A human booking agent: hand off any trip, they book and deliver tickets.",
  },
];

export default function PricingPage() {
  const { token, user } = useAuth();
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [portalUrl, setPortalUrl] = useState<string | null>(null);

  // ?checkout=success — Stripe redirected back after a completed payment.
  useEffect(() => {
    const p = new URLSearchParams(window.location.search).get("checkout");
    if (p === "success") setDone("Subscription started — your tier flips within a minute.");
    if (p === "cancelled") setDone("Checkout cancelled — nothing was charged.");
  }, []);

  async function startCheckout(tier: string) {
    if (!token) {
      window.location.href = `/auth/login?next=${encodeURIComponent("/pricing")}`;
      return;
    }
    setBusy(tier);
    setErr(null);
    try {
      const r = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/api/billing/checkout`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({ tier }),
        },
      );
      if (r.status === 503) {
        const j = await r.json().catch(() => ({}));
        setErr(j.detail || "Billing is not configured yet.");
        return;
      }
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        setErr(j.detail || `Checkout failed (${r.status})`);
        return;
      }
      const j = await r.json();
      window.location.href = j.url;
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Network error");
    } finally {
      setBusy(null);
    }
  }

  async function openPortal() {
    if (!token) {
      window.location.href = `/auth/login?next=${encodeURIComponent("/pricing")}`;
      return;
    }
    setBusy("portal");
    setErr(null);
    try {
      const r = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/api/billing/portal`,
        {
          method: "POST",
          headers: { Authorization: `Bearer ${token}` },
        },
      );
      if (r.status === 503 || r.status === 404) {
        const j = await r.json().catch(() => ({}));
        setErr(j.detail || "No active billing record.");
        return;
      }
      const j = await r.json();
      if (j.url) window.location.href = j.url;
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Network error");
    } finally {
      setBusy(null);
    }
  }

  return (
    <main className="min-h-screen bg-background text-foreground">
      <div className="mx-auto max-w-5xl px-6 py-12">
        <h1 className="text-3xl font-semibold">Plans</h1>
        <p className="mt-2 text-muted-foreground">
          Travel Scout runs on subscriptions. Free tier stays available (1 trip
          a month). Payment runs on Stripe&apos;s hosted checkout — the card
          never touches this site.
        </p>

        {user?.tier && user.tier !== "free" && (
          <div className="mt-4 rounded-lg border border-emerald-500/40 bg-emerald-500/10 px-4 py-2 text-sm">
            Current plan: <strong>{user.tier}</strong>
            <button
              onClick={openPortal}
              disabled={busy === "portal"}
              className="ml-3 rounded border border-border px-2 py-1 text-xs hover:bg-accent disabled:opacity-50"
            >
              Manage billing
            </button>
          </div>
        )}

        {done && (
          <div className="mt-4 rounded-lg border border-sky-500/40 bg-sky-500/10 px-4 py-2 text-sm">
            {done}
          </div>
        )}
        {err && (
          <div className="mt-4 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-2 text-sm">
            {err}
          </div>
        )}

        <div className="mt-8 grid gap-6 md:grid-cols-3">
          {TIERS.map((t) => (
            <div
              key={t.key}
              className="rounded-xl border border-border bg-card p-6"
            >
              <div className="text-sm text-muted-foreground">{t.name}</div>
              <div className="mt-1 text-2xl font-semibold">{t.price}</div>
              <p className="mt-3 text-sm text-muted-foreground">{t.blurb}</p>
              <button
                onClick={() => startCheckout(t.key)}
                disabled={busy !== null}
                className="mt-6 w-full rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              >
                {busy === t.key ? "Starting checkout…" : `Subscribe to ${t.name}`}
              </button>
            </div>
          ))}
        </div>

        <p className="mt-8 text-xs text-muted-foreground">
          Cancel or change plans any time from Stripe&apos;s billing portal.
          Booking-agent payments for handed-off trips are handled with your
          agent directly; the app records and confirms them.
        </p>
      </div>
    </main>
  );
}