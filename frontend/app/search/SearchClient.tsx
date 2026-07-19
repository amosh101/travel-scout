"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useSearchParams } from "next/navigation";
import { apiFetch, ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth-context";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type PitchItem = string;

interface Itinerary {
  rank: number;
  score: number;
  pitch: PitchItem[];
  destination: string;
  destination_country: string;
  start_date: string;
  end_date: string;
  duration_days: number;
  total_distance_km: number;
  races_in_window: Array<{
    name: string;
    circuit: string;
    city: string;
    country: string;
    starts_at: string;
  }>;
  holiday_alerts: Array<{ date: string; name: string; local: string }>;
  hotels: Array<{ name: string; lat: number; lon: number }>;
  route: { distance_km: number; duration_h: number } | null;
  sources: string[];
  missing: string[];
}

interface SearchResponse {
  query: Record<string, unknown>;
  geocoding: { origin: { name: string; lat: number; lon: number }; destination: { name: string; lat: number; lon: number } };
  results: Itinerary[];
  sources_used: string[];
  missing_data: string[];
}

export default function SearchClient() {
  const params = useSearchParams();
  const router = useRouter();
  const { token } = useAuth();
  const [data, setData] = useState<SearchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<number | null>(null);
  const [saved, setSaved] = useState<Record<number, string>>({});

  useEffect(() => {
    const url = `${API}/api/search?${params.toString()}`;
    setLoading(true);
    setError(null);
    fetch(url)
      .then((r) => {
        if (!r.ok) {
          return r.json().then((b) => {
            throw new Error(b.detail || `HTTP ${r.status}`);
          });
        }
        return r.json();
      })
      .then(setData)
      .catch((e) => setError(e.message || "Network error"))
      .finally(() => setLoading(false));
  }, [params]);

  if (loading) {
    return (
      <div className="py-12 text-center text-muted-foreground">
        Searching real-time data…
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-md border border-red-300 bg-red-50 p-4 text-sm text-red-900">
        <strong>Search failed.</strong> {error}
      </div>
    );
  }
  if (!data || data.results.length === 0) {
    return (
      <div className="rounded-md border border-border bg-card p-6 text-center text-muted-foreground">
        No itineraries matched. Try widening the date range or picking a
        different destination.
      </div>
    );
  }

  async function saveResult(it: Itinerary) {
    if (!token) {
      router.push("/auth/login");
      return;
    }
    setSaving(it.rank);
    try {
      const res = await apiFetch<{ id: string }>("/api/itineraries", {
        method: "POST",
        body: {
          title: `${it.destination}, ${it.destination_country} — ${it.start_date} → ${it.end_date}`,
          starts_at: `${it.start_date}T00:00:00Z`,
          ends_at: `${it.end_date}T00:00:00Z`,
          destination_country: it.destination_country,
          destination_name: it.destination,
          interests: [],
          anchor_event_ids: it.races_in_window.map((r) => `jolpica:${r.name}`),
          suggested_event_ids: it.holiday_alerts.map(
            (h) => `nager:${h.date}:${it.destination_country}:${h.name}`,
          ),
          search_params: Object.fromEntries(params.entries()),
          candidates: [it],
        },
      });
      setSaved((prev) => ({ ...prev, [it.rank]: res.id }));
    } catch (e) {
      if (e instanceof ApiError && e.status === 402) {
        alert("Tier limit reached for saved itineraries. Upgrade to keep more.");
      } else {
        alert(e instanceof Error ? e.message : "Save failed");
      }
    } finally {
      setSaving(null);
    }
  }

  return (
    <div className="space-y-6">
      <header className="rounded-md border border-border bg-card p-4 text-sm">
        <div>
          <span className="text-muted-foreground">Geocoded origin:</span>{" "}
          {data.geocoding.origin.name} ({data.geocoding.origin.lat.toFixed(3)},{" "}
          {data.geocoding.origin.lon.toFixed(3)})
        </div>
        <div>
          <span className="text-muted-foreground">Geocoded destination:</span>{" "}
          {data.geocoding.destination.name} ({data.geocoding.destination.lat.toFixed(3)},{" "}
          {data.geocoding.destination.lon.toFixed(3)})
        </div>
        <div className="mt-1 text-xs text-muted-foreground">
          Sources: {data.sources_used.join(", ")}
          {data.missing_data.length > 0 ? " · Missing: " + data.missing_data.join(", ") : ""}
        </div>
      </header>

      {data.results.map((it) => (
        <article
          key={it.rank}
          className="space-y-3 rounded-lg border border-border bg-card p-6"
        >
          <div className="flex items-baseline justify-between">
            <h3 className="text-lg font-semibold">
              #{it.rank} · {it.destination}, {it.destination_country}
            </h3>
            <div className="flex items-center gap-3">
              <div className="text-2xl font-semibold tabular-nums">
                {it.score.toFixed(1)} <span className="text-sm text-muted-foreground">/ 100</span>
              </div>
              {saved[it.rank] ? (
                <span className="rounded-md border border-green-500/40 bg-green-500/10 px-3 py-1 text-xs text-green-400">
                  Saved
                </span>
              ) : (
                <button
                  onClick={() => saveResult(it)}
                  disabled={saving === it.rank}
                  className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground disabled:opacity-50"
                >
                  {saving === it.rank ? "Saving…" : "Save trip"}
                </button>
              )}
            </div>
          </div>
          <div className="text-sm text-muted-foreground">
            {it.start_date} → {it.end_date} · {it.duration_days} day
            {it.duration_days === 1 ? "" : "s"}
            {it.route
              ? ` · ${it.route.distance_km.toFixed(0)} km · ${it.route.duration_h.toFixed(1)} h drive`
              : ""}
          </div>

          {it.pitch && it.pitch.length > 0 && (
            <ul className="text-sm space-y-1">
              {it.pitch.map((line, i) => (
                <li key={i} className="flex items-start gap-2">
                  <span className="mt-0.5 select-none text-amber-400">★</span>
                  <span>{line}</span>
                </li>
              ))}
            </ul>
          )}

          {it.races_in_window.length > 0 && (
            <section>
              <h4 className="text-sm font-semibold">F1 races in window</h4>
              <ul className="mt-1 text-sm text-muted-foreground">
                {it.races_in_window.map((r, i) => (
                  <li key={i}>
                    {r.name} — {r.circuit}, {r.city} ({r.country}) ·{" "}
                    {new Date(r.starts_at).toUTCString()}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {it.holiday_alerts.length > 0 && (
            <section>
              <h4 className="text-sm font-semibold text-amber-700">
                Public holidays in window
              </h4>
              <ul className="mt-1 text-sm text-amber-700">
                {it.holiday_alerts.map((h, i) => (
                  <li key={i}>
                    {h.date} — {h.name} ({h.local})
                  </li>
                ))}
              </ul>
            </section>
          )}

          {it.hotels.length > 0 && (
            <section>
              <h4 className="text-sm font-semibold">
                Hotels in destination (OSM)
              </h4>
              <ul className="mt-1 text-sm text-muted-foreground">
                {it.hotels.map((h, i) => (
                  <li key={i}>
                    {h.name} ({h.lat.toFixed(3)}, {h.lon.toFixed(3)})
                  </li>
                ))}
              </ul>
            </section>
          )}
        </article>
      ))}
    </div>
  );
}
