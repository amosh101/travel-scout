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

type Holiday = {
  date: string;
  name: string;
  local?: string;
  booking_link?: string;
};

type EventWindow = {
  kind: string;
  anchor_name: string;
  anchor_start: string;
  anchor_end: string;
  window_start: string;
  window_end: string;
};

type Itinerary = {
  id: string;
  title: string;
  starts_at: string;
  ends_at: string;
  destination_country: string | null;
  destination_name: string | null;
  destination_iata?: string | null;
  destination_country_alpha2?: string | null;
  origin?: string | null;
  origin_iata?: string | null;
  interests: string[];
  anchor_event_ids: string[];
  suggested_event_ids: string[];
  notes: string | null;
  currency: string;
  total_price_cents: number | null;
  anchor_events?: Race[];
  suggested_events?: Holiday[];   // T8d
  event_window?: EventWindow | null;  // T8a
  flights?: any[];
  hotels?: { name: string; lat: number; lon: number }[];
  route?: { distance_km: number } | null;
  pitch?: string[];
  score?: number;
  candidates?: any[];
  created_at: string;
  updated_at: string;
};

type ListResponse = {
  total: number;
  limit: number;
  offset: number;
  items: Itinerary[];
};

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

// Very small "city → IATA" table for outbound flight links. Coverage of
// the 50-chip catalog is enough; the rest fall back to the city name.
const IATA_BY_CITY: Record<string, string> = {
  maputo: "MPM",
  johannesburg: "JNB",
  "cape town": "CPT",
  durban: "DUR",
  windhoek: "WDH",
  gaborone: "GBE",
  lilongwe: "LLW",
  lusaka: "LUN",
  harare: "HRE",
  antananarivo: "TNR",
  mauritius: "MRU",
  "dar es salaam": "DAR",
  nairobi: "NBO",
  kigali: "KGL",
  lisbon: "LIS",
  porto: "OPO",
  madrid: "MAD",
  barcelona: "BCN",
  seville: "SVQ",
  paris: "CDG",
  lyon: "LYS",
  marseille: "MRS",
  london: "LHR",
  edinburgh: "EDI",
  amsterdam: "AMS",
  brussels: "BRU",
  antwerp: "ANR",
  berlin: "BER",
  munich: "MUC",
  hamburg: "HAM",
  zurich: "ZRH",
  geneva: "GVA",
  vienna: "VIE",
  salzburg: "SZG",
  rome: "FCO",
  florence: "FLR",
  milan: "MXP",
  venice: "VCE",
  naples: "NAP",
  athens: "ATH",
  istanbul: "IST",
  copenhagen: "CPH",
  stockholm: "ARN",
  oslo: "OSL",
  helsinki: "HEL",
  prague: "PRG",
  budapest: "BUD",
  warsaw: "WAW",
  krakow: "KRK",
  dublin: "DUB",
  reykjavik: "KEF",
  tokyo: "NRT",
  kyoto: "KIX",
  singapore: "SIN",
  bangkok: "BKK",
  bali: "DPS",
  dubai: "DXB",
  "abu dhabi": "AUH",
  doha: "DOH",
  "new york": "JFK",
  "los angeles": "LAX",
  "san francisco": "SFO",
  chicago: "ORD",
  "mexico city": "MEX",
  "buenos aires": "EZE",
  "sao paulo": "GRU",
  "rio de janeiro": "GIG",
  spa: "LGG", // closest major airport to Spa-Francorchamps
};

function iataFor(city: string | null | undefined): string | null {
  if (!city) return null;
  return IATA_BY_CITY[city.trim().toLowerCase()] ?? null;
}

function flightLinks(
  originIata: string | null,
  destIata: string | null,
  date: string,
) {
  // We accept IATA codes directly. The backend now stores origin_iata and
  // destination_iata on every saved itinerary (from the resolver), so the
  // front-end never has to do a string→IATA lookup.
  if (!originIata || !destIata) return null;
  const cleanDate = date.slice(0, 10);
  return {
    google: `https://www.google.com/travel/flights?q=Flights%20from%20${originIata}%20to%20${destIata}%20on%20${cleanDate}`,
    skyscanner: `https://www.skyscanner.com/transport/flights/${originIata.toLowerCase()}/${destIata.toLowerCase()}/${cleanDate.replace(/-/g, "")}`,
  };
}

function hotelLinks(dest: string | null, checkin: string, checkout: string) {
  if (!dest) return null;
  const q = encodeURIComponent(dest);
  return `https://www.booking.com/searchresults.html?ss=${q}&checkin=${checkin.slice(0, 10)}&checkout=${checkout.slice(0, 10)}`;
}

export default function SavedPage() {
  const router = useRouter();
  const { token, ready, setToken } = useAuth();
  const [data, setData] = useState<ListResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [handoffState, setHandoffState] = useState<Record<string, "idle" | "busy" | "ok" | "err">>({});
  const [handoffMsg, setHandoffMsg] = useState<Record<string, string>>({});

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
        const res = await apiFetch<ListResponse>("/api/itineraries");
        if (!cancelled) setData(res);
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) {
          setToken(null);
          router.push("/auth/login");
          return;
        }
        if (!cancelled) {
          setErr(e instanceof Error ? e.message : "Failed to load");
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

  async function del(id: string) {
    if (!confirm("Delete this trip?")) return;
    try {
      await apiFetch<void>(`/api/itineraries/${id}`, { method: "DELETE" });
      setData((prev) =>
        prev
          ? {
              ...prev,
              items: prev.items.filter((i) => i.id !== id),
              total: prev.total - 1,
            }
          : prev,
      );
    } catch (e) {
      alert(e instanceof Error ? e.message : "Delete failed");
    }
  }

  async function contactAgent(it: Itinerary) {
    setHandoffState((p) => ({ ...p, [it.id]: "busy" }));
    setHandoffMsg((p) => ({ ...p, [it.id]: "" }));
    try {
      const res = await apiFetch<{ queue_id: string; status: string; message: string }>(
        "/api/agent/queue",
        {
          method: "POST",
          body: { itinerary_id: it.id },
        },
      );
      setHandoffState((p) => ({ ...p, [it.id]: "ok" }));
      setHandoffMsg((p) => ({ ...p, [it.id]: res.message }));
    } catch (e) {
      setHandoffState((p) => ({ ...p, [it.id]: "err" }));
      setHandoffMsg((p) => ({
        ...p,
        [it.id]: e instanceof Error ? e.message : "Handoff failed",
      }));
    }
  }

  if (!ready) {
    return <p className="p-8 text-muted-foreground">Loading…</p>;
  }

  return (
    <main className="container max-w-4xl space-y-6 py-10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-3xl font-semibold">My saved trips</h1>
        <div className="flex gap-2">
          <Link
            href="/itineraries"
            className="rounded-md border border-border px-3 py-2 text-sm hover:bg-accent"
          >
            See more trips
          </Link>
          <Link
            href="/"
            className="rounded-md border border-border px-3 py-2 text-sm hover:bg-accent"
          >
            Plan a new trip
          </Link>
          <button
            onClick={() => {
              setToken(null);
              router.push("/");
            }}
            className="rounded-md border border-border px-3 py-2 text-sm hover:bg-accent"
          >
            Sign out
          </button>
        </div>
      </div>

      <p className="rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-200">
        MVP note: bookings go to Google Flights, Skyscanner, Booking.com, or
        the event&rsquo;s own site. Travel-Scout doesn&rsquo;t take a
        commission yet.
      </p>

      {loading && <p className="text-muted-foreground">Loading…</p>}
      {err && (
        <p className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-300">
          {err}
        </p>
      )}

      {data && data.items.length === 0 && !loading && (
        <div className="rounded-xl border border-dashed border-border p-10 text-center">
          <p className="text-muted-foreground">No saved trips yet.</p>
          <Link
            href="/itineraries"
            className="mt-3 inline-block rounded-md bg-gradient-to-r from-amber-400 to-rose-400 px-4 py-2 text-sm font-semibold text-background"
          >
            See trips for my interests
          </Link>
        </div>
      )}

      {data && data.items.length > 0 && (
        <ul className="space-y-4">
          {data.items.map((it) => {
            const fLinks = flightLinks(
              it.origin_iata ?? null,
              it.destination_iata ?? null,
              it.starts_at,
            );
            const hLink = hotelLinks(
              it.destination_name,
              it.starts_at,
              it.ends_at,
            );
            return (
              <li
                key={it.id}
                className="rounded-xl border border-border bg-card p-6"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="flex-1">
                    <h2 className="text-xl font-semibold">{it.title}</h2>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {fmtDate(it.starts_at)} → {fmtDate(it.ends_at)}
                      {it.destination_name && ` · ${it.destination_name}`}
                      {it.destination_country && ` (${it.destination_country})`}
                    </p>
                    {typeof it.score === "number" && (
                      <p className="mt-1 text-sm">
                        Match score:{" "}
                        <span className="font-semibold">
                          {it.score.toFixed(0)}/100
                        </span>
                      </p>
                    )}
                    {it.event_window && (
                      <p className="mt-1 text-xs text-amber-300">
                        Around {it.event_window.anchor_name} ({it.event_window.window_start} → {it.event_window.window_end})
                      </p>
                    )}
                    {it.pitch && it.pitch.length > 0 && (
                      <ul className="mt-2 space-y-1 text-sm">
                        {it.pitch.map((line, i) => (
                          <li key={i} className="flex items-start gap-2">
                            <span className="mt-0.5 select-none text-amber-400">★</span>
                            <span>{line}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <button
                    onClick={() => del(it.id)}
                    className="rounded-md border border-border px-3 py-1.5 text-xs hover:bg-red-500/10"
                  >
                    Delete
                  </button>
                </div>

                {it.interests.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {it.interests.map((i) => (
                      <span
                        key={i}
                        className="rounded-full border border-border bg-background px-2.5 py-0.5 text-xs"
                      >
                        {i}
                      </span>
                    ))}
                  </div>
                )}

                {it.event_window && (
                  <div className="mt-4 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-sm">
                    <p className="font-semibold text-amber-300">
                      Event window: {it.event_window.anchor_name}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Anchor: {fmtDate(it.event_window.anchor_start)}
                      {it.event_window.anchor_start !== it.event_window.anchor_end &&
                        ` → ${fmtDate(it.event_window.anchor_end)}`}
                      {" "}· Trip dates: {fmtDate(it.event_window.window_start)}
                      → {fmtDate(it.event_window.window_end)}
                    </p>
                  </div>
                )}

                {it.anchor_events && it.anchor_events.length > 0 && (
                  <div className="mt-4">
                    <h3 className="text-sm font-semibold text-amber-300">
                      Anchor events
                    </h3>
                    <ul className="mt-1 space-y-2 text-sm">
                      {it.anchor_events.map((r, i) => (
                        <li key={i} className="rounded-md border border-border/40 p-2">
                          <p>
                            <span className="font-medium">{r.name}</span>{" "}
                            &middot; {r.circuit ?? r.city}, {r.country} &middot;{" "}
                            {new Date(r.starts_at).toUTCString()}
                            {r.ends_at && new Date(r.starts_at).toISOString().slice(0,10) !== new Date(r.ends_at).toISOString().slice(0,10) && (
                              <> → {new Date(r.ends_at).toUTCString()}</>
                            )}
                          </p>
                          {r.booking_link && (
                            <a
                              href={r.booking_link}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="mt-1 inline-block text-xs text-amber-300 underline hover:text-amber-200"
                            >
                              {r.booking_label ?? "View & book"} ↗
                            </a>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {it.suggested_events && it.suggested_events.length > 0 && (
                  <div className="mt-4">
                    <h3 className="text-sm font-semibold text-rose-300">
                      Other events in your window
                    </h3>
                    <ul className="mt-1 space-y-2 text-sm">
                      {it.suggested_events.map((h, i) => (
                        <li key={i} className="rounded-md border border-border/40 p-2">
                          <p>
                            <span className="font-medium">{h.name}</span>
                            {h.local ? <> ({h.local})</> : null} &middot; {fmtDate(h.date)}
                          </p>
                          {h.booking_link && (
                            <a
                              href={h.booking_link}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="mt-1 inline-block text-xs text-rose-300 underline hover:text-rose-200"
                            >
                              View on Nager.Date ↗
                            </a>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {it.notes && (
                  <p className="mt-4 text-sm">{it.notes}</p>
                )}

                {/* Booking links — outbound, no commission */}
                <div className="mt-5 border-t border-border/60 pt-4">
                  <h3 className="text-sm font-semibold">Book yourself</h3>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {fLinks ? (
                      <>
                        <a
                          href={fLinks.google}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="rounded-md border border-border bg-background px-3 py-1.5 text-xs hover:bg-accent"
                        >
                          ✈ Google Flights ↗
                        </a>
                        <a
                          href={fLinks.skyscanner}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="rounded-md border border-border bg-background px-3 py-1.5 text-xs hover:bg-accent"
                        >
                          ✈ Skyscanner ↗
                        </a>
                      </>
                    ) : (
                      <span className="text-xs text-muted-foreground">
                        Flight booking unavailable — destination not in our
                        IATA map. Try{" "}
                        <a
                          className="underline"
                          target="_blank"
                          rel="noopener noreferrer"
                          href={`https://www.google.com/travel/flights?q=Flights%20to%20${encodeURIComponent(it.destination_name ?? "")}`}
                        >
                          Google Flights search
                        </a>
                        .
                      </span>
                    )}
                    {hLink && (
                      <a
                        href={hLink}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="rounded-md border border-border bg-background px-3 py-1.5 text-xs hover:bg-accent"
                      >
                        🏨 Booking.com ↗
                      </a>
                    )}
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground">
                    You book on the provider&rsquo;s site. We don&rsquo;t take
                    a fee on the MVP.
                  </p>
                </div>

                {/* T8e: hand off to a booking agent */}
                <div className="mt-4 border-t border-border/60 pt-4">
                  <h3 className="text-sm font-semibold">
                    Want a human to handle it?
                  </h3>
                  <p className="mt-1 text-xs text-muted-foreground">
                    We&rsquo;ll pass this trip to a booking agent. They&rsquo;ll
                    reach out within 1 business day to confirm dates, prices,
                    and get your travel documents.
                  </p>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <button
                      onClick={() => contactAgent(it)}
                      disabled={handoffState[it.id] === "busy" || handoffState[it.id] === "ok"}
                      className="rounded-md bg-gradient-to-r from-amber-400 to-rose-400 px-3 py-1.5 text-xs font-semibold text-background disabled:opacity-50"
                    >
                      {handoffState[it.id] === "busy"
                        ? "Sending…"
                        : handoffState[it.id] === "ok"
                          ? "✓ Sent to agent"
                          : "Contact booking agent"}
                    </button>
                    {handoffMsg[it.id] && (
                      <span
                        className={
                          handoffState[it.id] === "err"
                            ? "text-xs text-red-300"
                            : "text-xs text-green-300"
                        }
                      >
                        {handoffMsg[it.id]}
                      </span>
                    )}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </main>
  );
}
