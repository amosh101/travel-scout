"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
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
  const { token, ready, setToken } = useAuth();
  const [data, setData] = useState<DiscoverResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [savingRank, setSavingRank] = useState<number | null>(null);
  const [saved, setSaved] = useState<Record<number, string>>({});

  useEffect(() => {
    if (!ready) return;
    if (!token) {
      router.push("/auth/login");
      return;
    }
    let cancelled = false;
    async function load() {
      setLoading(true);
      setErr(null);
      try {
        const res = await apiFetch<DiscoverResponse>(
          "/api/itineraries/discover",
        );
        if (!cancelled) setData(res);
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) {
          setToken(null);
          router.push("/auth/login");
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
  }, [ready, token, router, setToken]);

  async function saveResult(r: Result) {
    if (!token) {
      router.push("/auth/login");
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
          <h1 className="text-3xl font-semibold">Your trips</h1>
          {data && (
            <>
              <p className="mt-1 text-sm text-muted-foreground">
                Based on your interests
                {data.interests.length > 0 && (
                  <>
                    {" "}— {data.interests.map((i) => i.name).join(", ")}
                  </>
                )}
                . {data.flight_status === "kiwi_not_configured" && (
                  <span className="ml-1 rounded bg-amber-500/10 px-1.5 py-0.5 text-amber-300">
                    Flight search requires API key (not configured)
                  </span>
                )}
              </p>
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
            Start over
          </Link>
        </div>
      </header>

      {loading && (
        <div className="space-y-4">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="rounded-xl border border-border bg-card p-6"
            >
              <div className="h-5 w-1/3 animate-pulse rounded bg-muted" />
              <div className="mt-3 h-3 w-2/3 animate-pulse rounded bg-muted/70" />
            </div>
          ))}
        </div>
      )}

      {err && (
        <div className="rounded-md border border-red-500/40 bg-red-500/10 p-4 text-sm text-red-300">
          {err}
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
                      Saved
                    </span>
                  ) : (
                    <button
                      onClick={() => saveResult(r)}
                      disabled={savingRank === r.rank}
                      className="rounded-md bg-gradient-to-r from-amber-400 to-rose-400 px-4 py-2 text-sm font-semibold text-background disabled:opacity-50"
                    >
                      {savingRank === r.rank ? "Saving…" : "Save this trip"}
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
    </main>
  );
}
