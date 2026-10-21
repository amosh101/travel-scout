"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { apiFetch, ApiError } from "../lib/api";
import { useAuth } from "../lib/auth-context";
import { GlassCard, GlassPill } from "@/components/glass";
import { useBackground } from "@/lib/background-store";
import { pickDefaultBackground } from "@/lib/backgrounds";

type Interest = { key: string; name: string };

type City = {
  id: string;
  name: string;
  ascii_name: string;
  country_alpha2: string;
  country_name: string;
  region: string | null;
  primary_iata: string | null;
  airports: Array<{ iata: string; name: string; priority: number }>;
  is_capital: boolean;
};

export default function HomePage() {
  const router = useRouter();
  const { token, ready } = useAuth();
  const bgInitialized = useRef(false);
  const [interests, setInterests] = useState<Interest[]>([]);
  const [cities, setCities] = useState<City[]>([]);
  const [originQuery, setOriginQuery] = useState("Maputo");
  const [originResolved, setOriginResolved] = useState<City | null>(null);
  const [originIata, setOriginIata] = useState<string | null>(null);
  const [pickedDestinations, setPickedDestinations] = useState<Set<string>>(
    new Set(),
  );
  const [pickedInterests, setPickedInterests] = useState<Set<string>>(
    new Set(),
  );
  const [otherInterest, setOtherInterest] = useState("");
  // Travel-when preset. "now" / "month" / "quarter" / "year" / "specific".
  // The first four expand into fixed date windows on the back-end.
  // "specific" reveals the date inputs and uses them verbatim.
  const [when, setWhen] = useState<"now" | "month" | "quarter" | "year" | "specific">("now");
  const today = new Date().toISOString().slice(0, 10);
  const monthFromNow = new Date(Date.now() + 30 * 24 * 3600 * 1000)
    .toISOString()
    .slice(0, 10);
  const [dateFrom, setDateFrom] = useState(today);
  const [dateTo, setDateTo] = useState(monthFromNow);
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Pick a default ambient background on mount only, NOT on every
  // render. Calling setBg() during render would cause re-renders that
  // cascade into "Maximum update depth exceeded". `claim()` tells
  // PageShell not to clobber our pick with the pathname default.
  useEffect(() => {
    if (bgInitialized.current) return;
    bgInitialized.current = true;
    const picked = pickDefaultBackground();
    const state = useBackground.getState();
    state.set({
      theme: picked.theme,
      variant: picked.variant,
      src: picked.src,
      palette: picked.palette,
      intensity: "vivid",
      override: true,
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [ints, dests] = await Promise.all([
          apiFetch<{ items: Interest[] }>("/api/profile/interests"),
          apiFetch<{ items: City[] }>("/api/refdata/cities?limit=200"),
        ]);
        if (!cancelled) {
          setInterests(ints.items);
          setCities(dests.items);
        }
      } catch (e) {
        if (!cancelled) {
          const msg =
            e instanceof Error ? e.message : "Failed to load options";
          setErr(msg);
        }
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  // Resolve origin via /api/refdata/resolve as the user types
  useEffect(() => {
    let cancelled = false;
    if (!originQuery || originQuery.length < 2) {
      setOriginResolved(null);
      setOriginIata(null);
      return;
    }
    const t = setTimeout(async () => {
      try {
        const res = await apiFetch<{
          matched: boolean;
          match_kind: string;
          city: City | null;
          airport: { iata: string } | null;
        }>(`/api/refdata/resolve?q=${encodeURIComponent(originQuery)}`);
        if (!cancelled) {
          setOriginResolved(res.matched ? res.city : null);
          setOriginIata(res.airport?.iata ?? null);
        }
      } catch {
        if (!cancelled) {
          setOriginResolved(null);
          setOriginIata(null);
        }
      }
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [originQuery]);

  function toggle<T>(set: Set<T>, value: T): Set<T> {
    const next = new Set(set);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    return next;
  }

  // Common origin presets — SADC + East Africa (the user's home region)
  const originPresets = cities
    .filter((c) =>
      ["MZ", "ZA", "TZ", "KE", "NA", "BW", "ZW", "ZM", "MW", "MG", "MU"].includes(
        c.country_alpha2,
      ),
    )
    .slice(0, 8);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    if (pickedInterests.size === 0 && !otherInterest.trim()) {
      setErr("Pick at least one interest — that's how we find your match.");
      return;
    }
    setSubmitting(true);
    try {
      const body = {
        origin: originQuery,
        destinations: Array.from(pickedDestinations),
        interests: Array.from(pickedInterests),
        interest_name: otherInterest.trim() || null,
        when: when,
        date_from: when === "specific" ? dateFrom : null,
        date_to: when === "specific" ? dateTo : null,
      };
      const res = await apiFetch<{ intent_id: string }>(
        "/api/profile/intake",
        { method: "POST", body },
      );
      // T9: logged-in users skip the registration form. We just apply
      // the new intake to the existing account (origin, destinations,
      // interests) and go straight to results.
      if (token) {
        try {
          await apiFetch(
            `/api/profile/intake/${encodeURIComponent(res.intent_id)}/apply`,
            { method: "POST" },
          );
        } catch (applyErr) {
          // If the apply call fails (expired intent, server error), still
          // send the user to /itineraries so they see their stored
          // profile results rather than a dead-end onboarding page.
          const msg =
            applyErr instanceof Error ? applyErr.message : "apply failed";
          console.warn("intake apply failed:", msg);
        }
        router.push("/itineraries");
        return;
      }
      router.push(`/onboarding?intent=${encodeURIComponent(res.intent_id)}`);
    } catch (e) {
      const msg =
        e instanceof ApiError && e.status === 422
          ? "Pick at least one interest"
          : e instanceof Error
            ? e.message
            : "Failed to start";
      setErr(msg);
      setSubmitting(false);
    }
  }

  return (
    <main className="min-h-screen text-white">
      {/* Auth state lives in the global AuthNav (PageShell) — the top-right
          sign-in/open-my-trips button used to sit here and duplicated it. */}

      <section className="container max-w-5xl pt-16 pb-10 sm:pt-24">
        <div className="flex flex-col items-center text-center">
          <GlassPill accent="#fcb864">
            <span className="text-amber-300">●</span> Interest-driven travel planning
          </GlassPill>
          <h1 className="mt-6 text-balance text-5xl font-semibold tracking-tight text-white drop-shadow-lg sm:text-6xl">
            Trips built around{" "}
            <span className="bg-gradient-to-r from-amber-300 to-rose-300 bg-clip-text text-transparent">
              what you love
            </span>
          </h1>
          <p className="mt-6 max-w-2xl text-balance text-lg text-white/85">
            Tell us what you&rsquo;re into &mdash; F1, jazz, public holidays,
            cycling, food &mdash; and we&rsquo;ll find the real-world dates and
            places where they line up. Real events, real flights, no fake
            suggestions.
          </p>
        </div>
      </section>

      <section className="container max-w-3xl pb-20">
        <form
          onSubmit={submit}
        >
        <GlassCard
          accent="#fcb864"
          variant="strong"
          className="p-6 sm:p-8"
        >
          <h2 className="text-xl font-semibold text-white">Where do you start?</h2>
          <p className="mt-1 text-sm text-white/70">
            Your home city, airport code (JNB, MPM), or nickname
            (joburg, schiphol). We&rsquo;ll resolve it.
          </p>
          <div className="relative mt-3">
            <input
              type="text"
              value={originQuery}
              onChange={(e) => setOriginQuery(e.target.value)}
              placeholder="Maputo, joburg, MPM, JNB…"
              className="w-full rounded-lg border border-white/20 bg-white/10 px-3 py-2.5 text-base focus:border-primary focus:outline-none"
              required
            />
            {originResolved && (
              <div className="mt-1.5 flex items-center gap-2 text-xs text-white/70">
                <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-emerald-300">
                  ✓ {originResolved.country_alpha2}
                </span>
                <span>
                  {originResolved.name}
                  {originResolved.region ? `, ${originResolved.region}` : ""}
                </span>
                {originIata && (
                  <span className="ml-auto rounded-md border border-white/20 bg-white/15 px-1.5 py-0.5 font-mono text-[10px]">
                    {originIata}
                  </span>
                )}
              </div>
            )}
            {originQuery.length >= 2 && !originResolved && (
              <p className="mt-1.5 text-xs text-amber-300/80">
                Not in our database yet — we&rsquo;ll still try to geocode it.
              </p>
            )}
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {originPresets.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => {
                  setOriginQuery(c.name);
                  setOriginResolved(c);
                  setOriginIata(c.primary_iata);
                }}
                className={`rounded-full border px-2.5 py-0.5 text-xs transition-colors ${
                  originQuery.toLowerCase() === c.name.toLowerCase()
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-white/20 bg-white/10 hover:bg-accent"
                }`}
              >
                {c.country_alpha2} {c.name}
              </button>
            ))}
          </div>

          <h2 className="mt-8 text-xl font-semibold">
            Destinations you like <span className="text-sm font-normal text-white/70">(optional)</span>
          </h2>
          <p className="mt-1 text-sm text-white/70">
            Tap any cities you&rsquo;d happily return to. {cities.length} real
            cities in our database. If you don&rsquo;t pick, we&rsquo;ll
            suggest based on your interests.
          </p>
          <div className="mt-3 flex max-h-40 flex-wrap gap-1.5 overflow-y-auto rounded-lg border border-white/20 bg-white/10 p-2">
            {cities.map((c) => {
              const label = `${c.name} (${c.country_alpha2})${c.primary_iata ? ` ✈${c.primary_iata}` : ""}`;
              const active = pickedDestinations.has(c.name);
              return (
                <button
                  key={c.id}
                  type="button"
                  onClick={() =>
                    setPickedDestinations(toggle(pickedDestinations, c.name))
                  }
                  className={`rounded-full border px-2.5 py-1 text-xs transition-colors ${
                    active
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-white/20 hover:bg-accent"
                  }`}
                  title={c.primary_iata ? `Primary airport: ${c.primary_iata}` : "No major airport"}
                >
                  {label}
                </button>
              );
            })}
          </div>

          <h2 className="mt-8 text-xl font-semibold">
            What are you into? <span className="text-sm font-normal text-rose-300">*</span>
          </h2>
          <p className="mt-1 text-sm text-white/70">
            At least one. These are how we find your match.
          </p>
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
            {interests.map((i) => {
              const active = pickedInterests.has(i.key);
              return (
                <button
                  key={i.key}
                  type="button"
                  onClick={() =>
                    setPickedInterests(toggle(pickedInterests, i.key))
                  }
                  className={`rounded-lg border px-3 py-2.5 text-left text-sm transition-all ${
                    active
                      ? "border-amber-400/60 bg-amber-400/10 text-amber-200"
                      : "border-white/20 bg-white/10 hover:border-amber-400/40"
                  }`}
                >
                  {i.name}
                </button>
              );
            })}
          </div>
          <div className="mt-3">
            <input
              type="text"
              value={otherInterest}
              onChange={(e) => setOtherInterest(e.target.value)}
              placeholder="Or type your own (e.g. kite surfing)"
              className="w-full rounded-lg border border-white/20 bg-white/10 px-3 py-2 text-sm focus:border-primary focus:outline-none"
            />
          </div>

          <div className="mt-8 rounded-lg border border-white/20 bg-white/10 p-4">
            <p className="text-sm font-medium">When are you going?</p>
            <p className="mt-0.5 text-xs text-white/70">
              We only look at events inside this window.
            </p>
            <div className="mt-3 inline-flex flex-wrap rounded-lg border border-white/20 bg-white/15 p-0.5 text-xs">
              {(
                [
                  ["now", "Next 2 weeks"],
                  ["month", "Next month"],
                  ["quarter", "Next 3 months"],
                  ["year", "Next 6 months"],
                  ["specific", "Pick dates"],
                ] as const
              ).map(([v, label]) => (
                <button
                  key={v}
                  type="button"
                  onClick={() => setWhen(v)}
                  className={`rounded-md px-3 py-1.5 font-medium transition-colors ${
                    when === v
                      ? "bg-primary text-primary-foreground"
                      : "text-white/70 hover:text-white"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            {when === "specific" && (
              <div className="mt-3 grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-white/70">From</label>
                  <input
                    type="date"
                    value={dateFrom}
                    onChange={(e) => setDateFrom(e.target.value)}
                    className="mt-1 w-full rounded-md border border-white/20 bg-white/10 px-2 py-1.5 text-sm"
                  />
                </div>
                <div>
                  <label className="text-xs text-white/70">To</label>
                  <input
                    type="date"
                    value={dateTo}
                    onChange={(e) => setDateTo(e.target.value)}
                    className="mt-1 w-full rounded-md border border-white/20 bg-white/10 px-2 py-1.5 text-sm"
                  />
                </div>
              </div>
            )}
          </div>

          {err && (
            <p className="mt-4 rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-300">
              {err}
            </p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="mt-6 w-full rounded-lg bg-gradient-to-r from-amber-400 to-rose-400 px-4 py-3 text-base font-semibold text-slate-900 transition-opacity disabled:opacity-50"
          >
            {submitting ? "One moment…" : "Find my trips →"}
          </button>
        </GlassCard>
        </form>
      </section>

      {/* Footer note */}
      <footer className="border-t border-white/10 py-8 text-center text-xs text-white/60">
        Real data only &middot; {cities.length} cities &middot; {interests.length} interests
        &middot; Jolpica F1 &middot; Nager.Date public holidays
        &middot; OpenStreetMap &middot; OSRM routing
      </footer>
    </main>
  );
}
