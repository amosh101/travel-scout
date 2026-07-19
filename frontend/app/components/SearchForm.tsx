"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

/**
 * Travel-Scout search form — landing page hero.
 * Posts to /api/search via the search page, not directly,
 * so the user can edit the URL or share the result.
 *
 * No budget input: pricing is intentionally absent from the result
 * page until we have real flight + hotel data wired in. Until then
 * the "how much will this cost?" question is answered by the
 * outbound booking links, not by a budget field that would be
 * filtered against a number the system doesn't actually compute.
 */
export default function SearchForm() {
  const router = useRouter();
  const [origin, setOrigin] = useState("Maputo");
  const [destination, setDestination] = useState("Johannesburg");
  const [startDate, setStartDate] = useState("2026-07-19");
  const [endDate, setEndDate] = useState("2026-07-22");

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const params = new URLSearchParams({
      origin,
      destination,
      start_date: startDate,
      end_date: endDate,
    });
    router.push(`/search?${params.toString()}`);
  }

  return (
    <form
      onSubmit={submit}
      className="w-full max-w-2xl space-y-4 rounded-lg border border-border bg-card p-6"
    >
      <h2 className="text-lg font-semibold">Plan a trip</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block text-sm">
          <span className="text-muted-foreground">From</span>
          <input
            type="text"
            value={origin}
            onChange={(e) => setOrigin(e.target.value)}
            required
            className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2"
            placeholder="Maputo"
          />
        </label>
        <label className="block text-sm">
          <span className="text-muted-foreground">To</span>
          <input
            type="text"
            value={destination}
            onChange={(e) => setDestination(e.target.value)}
            required
            className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2"
            placeholder="Johannesburg"
          />
        </label>
        <label className="block text-sm">
          <span className="text-muted-foreground">Start</span>
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            required
            className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2"
          />
        </label>
        <label className="block text-sm">
          <span className="text-muted-foreground">End</span>
          <input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            required
            className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2"
          />
        </label>
      </div>
      <button
        type="submit"
        className="w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
      >
        Search
      </button>
      <p className="text-xs text-muted-foreground">
        Live data: OpenStreetMap, Jolpica F1, Nager.Date holidays, OSRM routing.
        Flights and ticket events return a &quot;not configured&quot; error until you set
        KIWI_API_KEY and TICKETMASTER_API_KEY.
      </p>
    </form>
  );
}
