"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useSearchParams } from "next/navigation";
import { apiFetch, ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth-context";

type Race = {
  name: string;
  circuit?: string;
  city: string;
  country: string;
  starts_at: string;
  ends_at?: string | null;
  source_url?: string;
  booking_link?: string;
  booking_label?: string;
};

type Holiday = { date: string; name: string; local?: string; booking_link?: string };

type InterestEvent = {
  kind: string;
  title: string;
  date?: string | null;
  city?: string;
  country?: string;
  source?: string;
  source_url?: string;
};

type Result = {
  rank: number;
  score: number;
  pitch: string[];
  destination: string;
  destination_country: string;
  destination_iata?: string | null;
  destination_country_alpha2?: string | null;
  origin_iata?: string | null;
  start_date: string;
  end_date: string;
  duration_days: number;
  total_distance_km?: number;
  races_in_window: Race[];
  holiday_alerts: Holiday[];
  interest_events?: InterestEvent[];
  hotels: { name: string; lat: number; lon: number }[];
  route?: { distance_km: number } | null;
  sources: string[];
  missing: string[];
  event_window?: {
    kind: string;
    anchor_name: string;
    anchor_start: string;
    anchor_end: string;
    window_start: string;
    window_end: string;
  } | null;
};

type DiscoverResponse = {
  user: { id: string; email: string };
  interests: { key: string; name: string }[];
  anchors: {
    origin: string;
    origin_iata?: string | null;
    date_from: string;
    date_to: string;
    destination_override: string | null;
  };
  active_window?: {
    from: string;
    to: string;
    when: string | null;
    when_label: string | null;
  } | null;
  results: Result[];
  sources_used: string[];
  flight_status: string;
};

export default function ItinerariesPage() {
  const router = useRouter();
  const sp = useSearchParams();
  const { token, ready, setToken } = useAuth();
  const [data, setData] = useState<DiscoverResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [savingRank, setSavingRank] = useState<number | null>(null);
  const [saved, setSaved] = useState<Record<number, string>>({});
  // URL override destination (only set when ?destination= is in the URL).
  // Lifted out of the loader so render-time copy can branch on it.
  const urlDestination = sp?.get("destination") ?? null;
  const urlDateFrom = sp?.get("date_from") ?? null;
  const urlDateTo = sp?.get("date_to") ?? null;

  useEffect(() => {
    // Do NOT gate on token. The user wants to see the results first,
    // then get the "sign up to save" / "log in" prompt at the bottom.
    // If ?destination= is in the URL, use it (anonymous preview path);
    // otherwise the backend falls back to the user's stored profile.
    if (!ready) return;
    // Regression fix: the backend's anonymous discover branch REQUIRES
    // ?destination= (it 400s with "anonymous discover requires
    // ?destination=City"). A visitor with no session AND no destination
    // used to trigger that guaranteed 400 and this page rendered the raw
    // error — the "page loads but no itineraries" dead end. That state is
    // always a broken handoff: show the sign-up panel below instead of
    // calling an endpoint that cannot succeed.
    if (!token && !urlDestination) {
      setLoading(false);
      setErr("Log in to see itineraries built from your profile — or pick a destination to preview what you'd find.");
      return;
    }
    let cancelled = false;
    async function load() {
      setLoading(true);
      setErr(null);
      try {
        const params = new URLSearchParams();
        if (urlDestination) params.set("destination", urlDestination);
        if (urlDateFrom) params.set("date_from", urlDateFrom);
        if (urlDateTo) params.set("date_to", urlDateTo);
        const qs = params.toString();
        const res = await apiFetch<DiscoverResponse>(
          `/api/itineraries/discover${qs ? `?${qs}` : ""}`,
        );
        if (!cancelled) setData(res);
      } catch (e) {
        // Session-repair path: 401 means the backend rejected the
        // session outright; a 400 WITH a local token means the token was
        // stale/invalid and get_optional_user() silently downgraded the
        // request to the anonymous branch, which then 400'd on the
        // missing ?destination= (this was the owner-facing regression).
        // In both cases: clear the dead token and ask for a re-login.
        if (e instanceof ApiError && (e.status === 401 || (e.status === 400 && token))) {
          setToken(null);
          // Don't loop: effect re-runs with token=null and short-circuits
          // via the !token && !urlDestination guard above.
          setErr("Your session expired — log in again to see your itineraries.");
          return;
        }
        if (e instanceof ApiError && e.status === 400) {
          // Anonymous caller without a usable destination.
          setErr(
            "Pick a destination from the home page, or log in to see itineraries built from your profile.",
          );
          return;
        }
        if (e instanceof ApiError && e.status === 409) {
          setErr(
            "We don't have any interests on file for your account. Try the intake form again.",
          );
          return;
        }
        if (!cancelled) {
          setErr(e instanceof Error ? e.message : "Failed to load itineraries");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [ready, token, sp, setToken]);

  async function saveResult(r: Result) {
    if (!token) {
      // Anonymous: the results are already visible; tell the user
      // that saving requires a free account. Don't redirect — they
      // were just told to look at the results first.
      router.push(`/auth/login?next=/itineraries?destination=${encodeURIComponent(data?.anchors.destination_override ?? r.destination)}`);
      return;
    }
    setSavingRank(r.rank);
    try {
      const res = await apiFetch<{ id: string }>("/api/itineraries", {
        method: "POST",
        body: {
          title: `${r.destination}, ${r.destination_country} — ${r.start_date} → ${r.end_date}`,
          starts_at: `${r.start_date}T00:00:00Z`,
          ends_at: `${r.end_date}T00:00:00Z`,
          destination_country: r.destination_country,
          destination_name: r.destination,
          origin: data?.anchors.origin,
          origin_iata: r.origin_iata ?? data?.anchors.origin_iata ?? null,
          destination_iata: r.destination_iata ?? null,
          destination_country_alpha2: r.destination_country_alpha2 ?? null,
          interests: data?.interests.map((i) => i.key) ?? [],
          anchor_event_ids: r.races_in_window.map(
            (race) => `jolpica:${race.name}`,
          ),
          suggested_event_ids: r.holiday_alerts.map(
            (h) => `nager:${h.date}:${r.destination_country}:${h.name}`,
          ),
          search_params: {
            origin: data?.anchors.origin,
            date_from: data?.anchors.date_from,
            date_to: data?.anchors.date_to,
          },
          candidates: [r],
          anchor_events: r.races_in_window,
          suggested_events: r.holiday_alerts,  // T8d: full holiday details
          event_window: r.event_window,         // T8a: persist the window meta
          flights: [],
          hotels: r.hotels,
          route: r.route,
          pitch: r.pitch,
          score: r.score,
        },
      });
      setSaved((prev) => ({ ...prev, [r.rank]: res.id }));
    } catch (e) {
      if (e instanceof ApiError && e.status === 402) {
        alert(
          "You've hit the FREE tier limit (3 saved itineraries / month). Upgrade to keep more.",
        );
      } else {
        alert(e instanceof Error ? e.message : "Save failed");
      }
    } finally {
      setSavingRank(null);
    }
  }

  if (!ready) {
    return <p className="p-8 text-muted-foreground">Loading…</p>;
  }

  return (
    <main className="container max-w-5xl space-y-6 py-10">
      <header className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          {(() => {
            const browsingNew = !!urlDestination;
            const hasCity = data?.results?.[0]?.destination;
            // Three distinct states:
            //   1) Logged in browsing a specific new city → "Trips to <City>"
            //   2) Logged in on their home view (no override) → "Your trips"
            //   3) Anonymous → "Suggested trips" (original copy)
            // (We render the header once data is loaded; before that show
            // a neutral title.)
            const title = !data
              ? "Itineraries"
              : token
                ? browsingNew && hasCity
                  ? `Trips to ${data.anchors.destination_override ?? hasCity}`
                  : "Your trips"
                : "Suggested trips";
            return <h1 className="text-3xl font-semibold">{title}</h1>;
          })()}
          {data && (
            <>
              <p className="mt-1 text-sm text-muted-foreground">
                {token && data.interests.length > 0
                  ? <>Based on your interests — {data.interests.map((i) => i.name).join(", ")}.</>
                  : <>Based on the interests you picked.</>}
                {data.flight_status === "kiwi_not_configured" && (
                  <span className="ml-1 rounded bg-amber-500/10 px-1.5 py-0.5 text-amber-300">
                    Flight search requires API key (not configured)
                  </span>
                )}
              </p>
              {/*
                Below the intro, show one of three contextual lines:
                - logged in, browsing new city → "Pick one to shortlist it"
                - logged in, home view     → "Shortlist by saving"
                - anonymous                → "Log in to keep these across devices"
              */}
              {token && urlDestination ? (
                <p className="mt-1 text-xs text-muted-foreground">
                  New destination — pick one to shortlist it for{" "}
                  <span className="text-amber-300">
                    {data.anchors.destination_override ?? urlDestination}
                  </span>
                  . Saved trips stay in <em>My saved trips</em> alongside your other shortlists.
                </p>
              ) : token ? (
                <p className="mt-1 text-xs text-muted-foreground">
                  Save anything that catches your eye — it stays in{" "}
                  <em>My saved trips</em> across devices.
                </p>
              ) : (
                <p className="mt-1 text-xs text-muted-foreground">
                  Log in to see your saved trips and keep these across devices.
                </p>
              )}
              {data.active_window && (
                <p className="mt-1 text-xs text-muted-foreground">
                  Showing trips in your{" "}
                  <span className="text-amber-300">
                    {data.active_window.when_label || "selected"}
                  </span>
                  {" "}({data.active_window.from} → {data.active_window.to})
                </p>
              )}
            </>
          )}
        </div>
        <div className="flex gap-2">
          {/*
            Visible CTAs depend on state:
            - logged in: "My saved trips" + "Find another city" (we
              shouldn't say "Start over" — that's a punishment tone for
              someone who already has an account)
            - anonymous: "My saved trips" (or login?) + "Start over"
          */}
          <Link
            href="/saved"
            className="rounded-md border border-border px-3 py-2 text-sm hover:bg-accent"
          >
            My saved trips
          </Link>
          <Link
            href="/"
            className="rounded-md border border-border px-3 py-2 text-sm hover:bg-accent"
          >
            {token ? "Find another city" : "Start over"}
          </Link>
        </div>
      </header>

      {loading && (
        <div className="space-y-4" role="status" aria-live="polite">
          <div className="rounded-lg border border-border/40 bg-card/30 p-4">
            <p className="text-sm text-muted-foreground">
              <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-amber-400" />
              {" "}Finding the best options for you…
            </p>
            <p className="mt-1 text-xs text-muted-foreground/70">
              Pulling real-time events, holidays, and hotels from public
              sources. Usually under 2 seconds.
            </p>
          </div>
          <ul className="space-y-4">
            {[0, 1, 2].map((i) => (
              <li
                key={i}
                className="rounded-xl border border-border bg-card p-6"
              >
                <div className="h-5 w-1/3 animate-pulse rounded bg-muted" />
                <div className="mt-3 h-3 w-2/3 animate-pulse rounded bg-muted/70" />
              </li>
            ))}
          </ul>
        </div>
      )}

      {err && (
        <div className="rounded-md border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-300">
          {err}
        </div>
      )}

      {/* Session-expired / no-session recovery: always give the user an
          exit from this page. Shown only when there's no session — a
          signed-in user who sees an error has other things to fix and
          the bottom panels below still handle their case. */}
      {err && !token && (
        <div className="flex flex-wrap gap-2">
          <Link
            href="/auth/login?next=/itineraries"
            className="rounded-md bg-gradient-to-r from-amber-400 to-rose-400 px-4 py-2 text-sm font-semibold text-background"
          >
            Log in
          </Link>
          <Link
            href="/auth/register?next=/itineraries"
            className="rounded-md border border-border px-4 py-2 text-sm hover:bg-accent"
          >
            Sign up — it&apos;s free
          </Link>
        </div>
      )}

      {data && data.results.length === 0 && !loading && (
        <div className="rounded-xl border border-dashed border-border p-10 text-center">
          <p className="text-muted-foreground">
            No matches for those interests in the next 6 months.
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            Try widening the date range or removing some destinations.
          </p>
        </div>
      )}

      {data && data.results.length > 0 && (
        <ul className="space-y-5">
          {data.results.map((r) => {
            return (
            <li
              key={r.rank}
              className="rounded-xl border border-border bg-card p-6"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <p className="text-xs text-muted-foreground">#{r.rank}</p>
                  <h2 className="text-2xl font-semibold">
                    {r.destination}, {r.destination_country}
                  </h2>
                  <p className="text-sm text-muted-foreground">
                    {r.start_date} → {r.end_date} &middot; {r.duration_days} day
                    {r.duration_days === 1 ? "" : "s"}
                    {r.route
                      ? ` · ${r.route.distance_km.toFixed(0)} km from origin`
                      : ""}
                  </p>
                  {r.event_window && (
                    <p className="mt-1 text-xs text-amber-300">
                      Around {r.event_window.anchor_name} ({r.event_window.window_start} → {r.event_window.window_end})
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-3">
                  {typeof r.score === "number" && (
                    <div className="text-right">
                      <div className="text-2xl font-semibold tabular-nums">
                        {r.score.toFixed(0)}
                      </div>
                      <div className="text-xs text-muted-foreground">/ 100</div>
                    </div>
                  )}
                  {saved[r.rank] ? (
                    <span className="rounded-md border border-green-500/40 bg-green-500/10 px-3 py-1.5 text-xs text-green-300">
                      Shortlisted
                    </span>
                  ) : (
                    <button
                      onClick={() => saveResult(r)}
                      disabled={savingRank === r.rank}
                      className="rounded-md bg-gradient-to-r from-amber-400 to-rose-400 px-4 py-2 text-sm font-semibold text-background disabled:opacity-50"
                    >
                      {savingRank === r.rank
                        ? "Shortlisting…"
                        : token
                          ? "Shortlist this trip"
                          : "Save this trip"}
                    </button>
                  )}
                </div>
              </div>

              {r.pitch.length > 0 && (
                <ul className="mt-4 space-y-1 text-sm">
                  {r.pitch.map((line, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <span className="mt-0.5 select-none text-amber-400">★</span>
                      <span>{line}</span>
                    </li>
                  ))}
                </ul>
              )}

              {r.races_in_window.length > 0 && (
                <div className="mt-4">
                  <h3 className="text-sm font-semibold text-amber-300">
                    Anchor events (F1 races)
                  </h3>
                  <ul className="mt-1 space-y-1 text-sm">
                    {r.races_in_window.map((race, i) => (
                      <li key={i}>
                        <span className="font-medium">{race.name}</span> &middot;{" "}
                        {race.circuit ?? race.city}, {race.country} &middot;{" "}
                        {new Date(race.starts_at).toUTCString()}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {r.holiday_alerts.length > 0 && (
                <div className="mt-4">
                  <h3 className="text-sm font-semibold text-rose-300">
                    Other events in your window (public holidays)
                  </h3>
                  <ul className="mt-1 space-y-1 text-sm">
                    {r.holiday_alerts.map((h, i) => (
                      <li key={i}>
                        <span className="font-medium">{h.name}</span>{" "}
                        {h.local ? <>({h.local})</> : null} &middot; {h.date}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {r.interest_events && r.interest_events.length > 0 && (
                <div className="mt-4">
                  <h3 className="text-sm font-semibold text-emerald-300">
                    Events matching your interests
                  </h3>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Free event data from Wikidata and Wikipedia — verify dates
                    with the source before booking.
                  </p>
                  <ul className="mt-2 space-y-1 text-sm">
                    {r.interest_events
                      .filter(
                        (e) =>
                          e.source !== "jolpica" &&
                          e.source !== "nager.date"
                      )
                      .map((e, i) => (
                        <li key={i}>
                          <span className="font-medium">{e.title}</span>
                          {e.city ? <> &middot; {e.city}</> : null}
                          {e.date ? <> &middot; {e.date}</> : null}
                          {e.source ? (
                            <span className="text-xs text-muted-foreground">
                              {" "}
                              ({e.source})
                            </span>
                          ) : null}
                          {e.source_url ? (
                            <>
                              {" "}
                              <a
                                href={e.source_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-xs text-sky-400 hover:underline"
                              >
                                source ↗
                              </a>
                            </>
                          ) : null}
                        </li>
                      ))}
                  </ul>
                </div>
              )}

              {r.hotels.length > 0 && (
                <div className="mt-4">
                  <h3 className="text-sm font-semibold">Where to stay (OSM)</h3>
                  <ul className="mt-1 space-y-1 text-sm text-muted-foreground">
                    {r.hotels.slice(0, 5).map((h, i) => (
                      <li key={i}>
                        {h.name} ({h.lat.toFixed(3)}, {h.lon.toFixed(3)})
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {/* Booking — only on the saved view; results page just shows the trip */}
            </li>
            );
          })}
        </ul>
      )}

      {/* Bottom panel: copy depends on auth state + whether they're
          browsing a new destination. Three states:
          1. Logged in + browsing new city → "Shortlist looks good? Already saved."
          2. Logged in + home view         → "Browse another city"
          3. Anonymous                      → keep the original sign-up pitch (P16 contract) */}
      {data && data.results.length > 0 && !loading && token && urlDestination && (
        <div className="mt-6 rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-5">
          <h2 className="text-lg font-semibold text-emerald-300">
            Already shortlisted — keep exploring
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Anything you shortlisted for{" "}
            <span className="text-amber-300">
              {data.anchors.destination_override ?? urlDestination}
            </span>{" "}
            is in <em>My saved trips</em>. Compare it against other cities:
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Link
              href="/saved"
              className="rounded-md bg-gradient-to-r from-amber-400 to-rose-400 px-4 py-2 text-sm font-semibold text-background"
            >
              Open my saved trips
            </Link>
            <Link
              href="/"
              className="rounded-md border border-border px-4 py-2 text-sm hover:bg-accent"
            >
              Find another city
            </Link>
          </div>
        </div>
      )}

      {data && data.results.length > 0 && !loading && token && !urlDestination && (
        <div className="mt-6 rounded-xl border border-border bg-card/30 p-5">
          <p className="text-sm text-muted-foreground">
            Looking for somewhere new?{" "}
            <Link href="/" className="text-amber-300 hover:underline">
              Pick another city
            </Link>{" "}
            and I’ll re-rank these for you.
          </p>
        </div>
      )}

      {/* Anonymous: keep the sign-up pitch. P16 contract: data shown first, gate the write. */}
      {data && data.results.length > 0 && !loading && !token && (
        <div className="mt-6 rounded-xl border border-amber-500/30 bg-amber-500/5 p-5">
          <h2 className="text-lg font-semibold text-amber-300">
            Keep these {data.results.length === 1 ? "trip" : "trips"}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            You found {data.results.length} ready-made itinerar{data.results.length === 1 ? "y" : "ies"}.
            Already have an account? Log in to save them. New here? Sign up in
            seconds — it’s free.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Link
              href={`/auth/login?next=/itineraries${sp?.toString() ? `?${sp.toString()}` : ""}`}
              className="rounded-md bg-gradient-to-r from-amber-400 to-rose-400 px-4 py-2 text-sm font-semibold text-background"
            >
              Log in — save your trips
            </Link>
            <Link
              href={`/auth/register?next=/itineraries${sp?.toString() ? `?${sp.toString()}` : ""}`}
              className="rounded-md border border-border px-4 py-2 text-sm hover:bg-accent"
            >
              Sign up — it’s free
            </Link>
          </div>
        </div>
      )}
    </main>
  );
}
