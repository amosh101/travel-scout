"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { apiFetch, ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth-context";

type Interest = { key: string; name: string };

type PreviewResult = {
  rank: number;
  score: number;
  destination: string;
  destination_country: string | null;
  start_date: string;
  end_date: string;
  duration_days: number;
  total_distance_km: number;
  races_in_window: unknown[] | null;
  interest_events: unknown[] | null;
  holiday_alerts: { date: string; name: string }[] | null;
};

function OnboardingInner() {
  const router = useRouter();
  const params = useSearchParams();
  const intentId = params.get("intent") || "";
  const { token, ready, setToken } = useAuth();

  const [interests, setInterests] = useState<Interest[]>([]);
  const [intake, setIntake] = useState<{
    origin: string;
    destinations: string[];
    interests: string[];
    interest_name: string | null;
    travel_soon: boolean;
    when?: string;
    when_label?: string;
    date_from: string | null;
    date_to: string | null;
  } | null>(null);

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [address, setAddress] = useState("");
  const [password, setPassword] = useState("");
  const [referrer, setReferrer] = useState("");
  // T8f: international-travel document fields (all optional)
  const [nationality, setNationality] = useState("");
  const [passportNumber, setPassportNumber] = useState("");
  const [passportExpiry, setPassportExpiry] = useState("");
  const [passportIssuingCountry, setPassportIssuingCountry] = useState("");
  const [dateOfBirth, setDateOfBirth] = useState("");
  const [emergencyContactName, setEmergencyContactName] = useState("");
  const [emergencyContactPhone, setEmergencyContactPhone] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Post-selection auth (2026-10-22): the account forms no longer render at
  // search time. They appear ONLY after the visitor selects one of the
  // previewed itineraries — login ("Already have an account") on top, then
  // "or, tell us about yourself" with the creation form under it.
  const [sel, setSel] = useState<number | null>(null);
  const [lemail, setLemail] = useState("");
  const [lpass, setLpass] = useState("");
  const [lbusy, setLbusy] = useState(false);
  const [lerr, setLerr] = useState<string | null>(null);
  const authRef = useRef<HTMLDivElement>(null);

  // When a trip is selected, bring the auth panel into view.
  useEffect(() => {
    if (sel === null) return;
    authRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [sel]);

  async function loginSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!intentId) return;
    setLerr(null);
    setLbusy(true);
    try {
      const res = await apiFetch<{ access_token: string }>("/api/auth/login", {
        method: "POST",
        body: { email: lemail.trim(), password: lpass },
      });
      setToken(res.access_token);
      // Apply the visitor's selections to the now-authenticated account so
      // /itineraries builds from the profile they just searched with.
      try {
        await apiFetch(
          `/api/profile/intake/${encodeURIComponent(intentId)}/apply`,
          { method: "POST", accessToken: res.access_token },
        );
      } catch (applyErr) {
        console.warn("intake apply failed:", applyErr);
      }
      router.push("/itineraries");
    } catch (e) {
      setLerr(
        e instanceof ApiError && e.status === 401
          ? "Wrong email or password."
          : e instanceof Error
            ? e.message
            : "Login failed",
      );
      setLbusy(false);
    }
  }

  // Load intake + interests catalog for display.
  useEffect(() => {
    if (!intentId) {
      setErr("No intake id — go back to the landing page and start again.");
      return;
    }
    let cancelled = false;
    async function load() {
      try {
        const [ints, intakeData] = await Promise.all([
          apiFetch<{ items: Interest[] }>("/api/profile/interests"),
          apiFetch<{
            origin: string;
            destinations: string[];
            interests: string[];
            interest_name: string | null;
            travel_soon: boolean;
            when?: string;
            when_label?: string;
            date_from: string | null;
            date_to: string | null;
          }>(`/api/profile/intake/${intentId}`),
        ]);
        if (!cancelled) {
          setInterests(ints.items);
          setIntake(intakeData);
        }
      } catch (e) {
        if (!cancelled) {
          setErr(
            e instanceof Error
              ? `Couldn't load your selections: ${e.message}. Go back to the landing page and start again.`
              : "Couldn't load your selections. Go back to the landing page and start again.",
          );
        }
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [intentId]);

  // T9: a logged-in user who lands here (e.g. via stale bookmark, or by
  // following an old link) should never see the registration form.
  // Apply their intake to the existing account and go to results.
  useEffect(() => {
    if (!ready || !token || !intentId) return;
    let cancelled = false;
    (async () => {
      try {
        await apiFetch(
          `/api/profile/intake/${encodeURIComponent(intentId)}/apply`,
          { method: "POST" },
        );
      } catch (e) {
        // Ignore — we'll still send them to /itineraries so they see
        // their stored profile results.
        console.warn("intake apply failed:", e);
      }
      if (!cancelled) router.push("/itineraries");
    })();
    return () => {
      cancelled = true;
    };
  }, [ready, token, intentId, router]);

  // Anonymous preview build (2026-10-21): this page used to show an
  // eternal "working on it" spinner for anonymous visitors — nothing
  // was actually running in the background, and the intake contract
  // has no completion flag (the build only happens after registration
  // applies the profile). Two passes:
  //   1. destination pass — discover with the picked destination; on
  //      success the visitor is redirected STRAIGHT to the full
  //      itineraries page (2026-10-22, Sir: no intermediary preview,
  //      no secondary "open full results" button). The URL carries
  //      origin + window + interests + the intake id so the full page
  //      rebuilds the same personalised results and registration still
  //      attaches the selections.
  //   2. interest-anchored pass — events seeded from the real season
  //      calendar when no destination was picked OR the destination
  //      pass came back empty. The visitor always sees actual results.
  const [preview, setPreview] = useState<PreviewResult[]>([]);
  const [previewMode, setPreviewMode] = useState<"dest" | "interest" | null>(
    null,
  );
  const [previewState, setPreviewState] = useState<
    "loading" | "ready" | "no-dest" | "error"
  >("loading");
  const [previewErr, setPreviewErr] = useState<string | null>(null);

  useEffect(() => {
  // Signed-in visitors are handled by the T9 effect above. Running the
  // anonymous build for them would only fire a wasted discover call
  // (and race their apply-and-redirect navigation).
  if (!intake || token) return;
  const dest = intake.destinations[0] || null;
  // The discover contract takes CATALOG KEYS (the interests table's
  // key column) — Wikidata/Wikipedia route SPARQL on them. The
  // free-text "other" interest is passed as-is.
  const interestKeys: string[] = intake.interests.slice();
  if (intake.interest_name) interestKeys.push(intake.interest_name);
  if (!dest && interestKeys.length === 0) {
    setPreviewState("no-dest");
    return;
  }
    let cancelled = false;
    const common = new URLSearchParams();
    if (intake.origin) common.set("origin", intake.origin);
    if (intake.date_from) common.set("date_from", intake.date_from);
    if (intake.date_to) common.set("date_to", intake.date_to);
    (async () => {
      if (dest) {
        const qs = new URLSearchParams(common);
        qs.set("destination", dest);
        if (interestKeys.length) qs.set("interests", interestKeys.join(","));
        try {
          const res = await apiFetch<{ results: PreviewResult[] }>(
            `/api/itineraries/discover?${qs.toString()}`,
          );
          const results = res.results ?? [];
          if (cancelled) return;
          if (results.length > 0) {
            // Straight to the full results (2026-10-22, Sir): the URL
            // carries destination + window + origin + interests + the
            // intake id, so the full page rebuilds the same personalised
            // build (warm caches → fast) and the sign-up there can still
            // attach the selections via intake_id.
            qs.set("intent", intentId);
            router.replace(`/itineraries?${qs.toString()}`);
            return;
          }
        } catch {
          // fall through to the interest-anchored pass
        }
      }
      if (interestKeys.length > 0) {
        const qs = new URLSearchParams(common);
        qs.set("interests", interestKeys.join(","));
        qs.set("top_n", "3");
        try {
          const res = await apiFetch<{ results: PreviewResult[] }>(
            `/api/itineraries/discover?${qs.toString()}`,
          );
          if (!cancelled) {
            setPreview(res.results ?? []);
            setPreviewMode("interest");
            setPreviewState("ready");
          }
        } catch (e) {
          if (!cancelled) {
            setPreviewErr(
              e instanceof ApiError && e.status === 404
                ? "No dated events for these interests in this window yet. Add a destination, widen the dates, or pick an interest our sources cover (motorsport, music, food-wine, film, literature, art, sport)."
                : e instanceof Error
                  ? e.message
                  : "Preview build failed",
            );
            setPreviewState("error");
          }
        }
        return;
      }
      if (!cancelled) {
        setPreview([]);
        setPreviewMode("dest");
        setPreviewState("ready");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [intake, interests, token, intentId, router]);

  const pickedNames = intake
    ? interests
        .filter((i) => intake.interests.includes(i.key))
        .map((i) => i.name)
    : [];

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!intentId) return;
    setErr(null);
    if (password.length < 12) {
      setErr("Password must be at least 12 characters.");
      return;
    }
    setBusy(true);
    try {
      const res = await apiFetch<{ access_token: string }>(
        "/api/auth/register",
        {
          method: "POST",
          body: {
            intake_id: intentId,
            email: email.trim(),
            password,
            name: name.trim(),
            phone: phone.trim() || undefined,
            address: address.trim() || undefined,
            referrer: referrer.trim() || undefined,
            // T8f: travel docs (all optional, sent only if filled)
            ...(nationality.trim() && { nationality: nationality.trim().toUpperCase() }),
            ...(passportNumber.trim() && { passport_number: passportNumber.trim() }),
            ...(passportExpiry && { passport_expiry: passportExpiry }),
            ...(passportIssuingCountry.trim() && { passport_issuing_country: passportIssuingCountry.trim().toUpperCase() }),
            ...(dateOfBirth && { date_of_birth: dateOfBirth }),
            ...(emergencyContactName.trim() && { emergency_contact_name: emergencyContactName.trim() }),
            ...(emergencyContactPhone.trim() && { emergency_contact_phone: emergencyContactPhone.trim() }),
          },
        },
      );
      setToken(res.access_token);
      router.push("/itineraries");
    } catch (e) {
      const msg =
        e instanceof ApiError
          ? e.status === 409
            ? "That email is already registered. Try signing in."
            : e.status === 422
              ? "Password must be at least 12 characters."
              : `Registration failed (${e.status})`
          : e instanceof Error
            ? e.message
            : "Registration failed";
      setErr(msg);
      setBusy(false);
    }
  }

  return (
    <main className="min-h-screen bg-gradient-to-b from-background via-background to-muted/30">
      {/* Step 1: the build — honest state machine. loading = the real
          anonymous discover call is in flight; ready = show its actual
          results; no-dest = explain what is needed; error = show it and
          keep the register path (which builds from the saved profile)
          available below. */}
      <section className="container max-w-4xl pt-16 pb-10">
        <div className="text-center">
          {previewState === "loading" && (
            <>
              <div className="mx-auto inline-flex h-12 w-12 animate-spin items-center justify-center rounded-full border-2 border-amber-400/30 border-t-amber-400" />
              <h1 className="mt-6 text-3xl font-semibold tracking-tight sm:text-4xl">
                Working on your best itineraries
              </h1>
              <p className="mt-3 text-muted-foreground">
                Cross-referencing real events, public holidays, race dates, and
                venues across your interests.
              </p>
            </>
          )}
          {previewState === "ready" && (
            <>
              <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
                {previewMode === "interest"
                  ? "Trips built around your interests"
                  : `Trips matched to ${intake?.destinations[0] ?? ""}`}
              </h1>
              <p className="mt-3 text-muted-foreground">
                {previewMode === "interest"
                  ? "Anchored on real event dates in your window. Select a trip to keep it."
                  : "Built from real events, public holidays, race dates, and venues. Select a trip to keep it."}
              </p>
            </>
          )}
          {previewState === "no-dest" && (
            <>
              <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
                One thing before we build
              </h1>
              <p className="mt-3 text-muted-foreground">
                You didn&apos;t pick a destination, so there is nothing to
                preview yet. Pick at least one destination on the landing page
                and search again.
              </p>
            </>
          )}
          {previewState === "error" && (
            <>
              <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
                The preview build didn&apos;t finish
              </h1>
              <p className="mt-3 text-muted-foreground">
                {previewErr ?? "Something went wrong building a preview."} Try
                again, or refine your search on the landing page.
              </p>
            </>
          )}
        </div>

        {previewState === "loading" && (
          <div className="mt-10 grid gap-4 sm:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="rounded-xl border border-border bg-card/60 p-5"
              >
                <div className="h-4 w-1/2 animate-pulse rounded bg-muted" />
                <div className="mt-3 h-3 w-full animate-pulse rounded bg-muted/70" />
                <div className="mt-2 h-3 w-3/4 animate-pulse rounded bg-muted/50" />
                <div className="mt-4 flex gap-2">
                  <div className="h-5 w-12 animate-pulse rounded-full bg-muted/60" />
                  <div className="h-5 w-16 animate-pulse rounded-full bg-muted/60" />
                </div>
              </div>
            ))}
          </div>
        )}

        {previewState === "ready" && (
          <div className="mt-10 space-y-4">
            {preview.length === 0 ? (
              <div className="rounded-xl border border-border bg-card p-6 text-center sm:p-8">
                <p className="text-sm text-muted-foreground">
                  No trips matched your interests in this window. Try
                  different interests or dates on the landing page.
                </p>
              </div>
            ) : (
              <>
                <ul className="space-y-3">
                  {preview.map((r) => {
                    const evCount =
                      (r.races_in_window?.length ?? 0) +
                      (r.interest_events?.length ?? 0);
                    const holCount = r.holiday_alerts?.length ?? 0;
                    return (
                      <li
                        key={r.rank}
                        className={`rounded-xl border bg-card p-5 sm:p-6 ${
                          sel === r.rank ? "border-amber-400/60" : "border-border"
                        }`}
                      >
                        <div className="flex flex-wrap items-baseline justify-between gap-2">
                          <h2 className="text-lg font-semibold">
                            #{r.rank} {r.destination}
                            {r.destination_country
                              ? `, ${r.destination_country}`
                              : ""}
                          </h2>
                          <span className="flex items-center gap-3">
                            <span className="text-sm font-medium">
                              {r.score} / 100
                            </span>
                            <button
                              type="button"
                              onClick={() => setSel(r.rank)}
                              aria-pressed={sel === r.rank}
                              className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                                sel === r.rank
                                  ? "bg-amber-400/15 text-amber-200 ring-1 ring-amber-400/60"
                                  : "bg-primary text-primary-foreground hover:opacity-90"
                              }`}
                            >
                              {sel === r.rank ? "Selected ✓" : "Select this trip"}
                            </button>
                          </span>
                        </div>
                        <p className="mt-1 text-sm text-muted-foreground">
                          {r.start_date} → {r.end_date} · {r.duration_days}{" "}
                          days
                          {r.total_distance_km > 0
                            ? ` · ${Math.round(r.total_distance_km)} km from origin`
                            : ""}
                        </p>
                        <p className="mt-1 text-sm">
                          {evCount} event{evCount === 1 ? "" : "s"} ·{" "}
                          {holCount} public holiday{holCount === 1 ? "" : "s"}{" "}
                          in your window
                        </p>
                      </li>
                    );
                  })}
                </ul>
                {/* 2026-10-22 (Sir): the destination-mode "Open your full
                    results" intermediary is gone — those visitors are
                    redirected straight to /itineraries during the build.
                    Only the interest-anchored fallback (no destination) or
                    an empty window still renders here. */}
                {previewMode === "interest" && (
                  <p className="text-sm text-muted-foreground">
                    Select the trip you want and we&apos;ll hold it to your
                    account.
                  </p>
                )}
              </>
            )}
          </div>
        )}
      </section>

      {/* Post-selection auth panel (2026-10-22): hidden entirely until the
          visitor selects one of the previewed itineraries. Login on top,
          creation form under it. */}
      {sel !== null && (
      <section ref={authRef} className="container max-w-2xl scroll-mt-20 pb-20">
        <div className="space-y-8 rounded-2xl border border-border bg-card p-6 shadow-xl sm:p-8">
          {/* Already have an account → login */}
          <div>
            <h2 className="text-xl font-semibold">Already have an account</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Log in and your selections will be applied to it.
            </p>
            <form onSubmit={loginSubmit} className="mt-4 space-y-4">
              <Field
                label="Email address"
                type="email"
                value={lemail}
                onChange={setLemail}
                required
                autoComplete="email"
              />
              <Field
                label="Password"
                type="password"
                value={lpass}
                onChange={setLpass}
                required
                autoComplete="current-password"
              />
              {lerr && (
                <p className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-300">
                  {lerr}
                </p>
              )}
              <button
                type="submit"
                disabled={lbusy}
                className="w-full rounded-lg bg-gradient-to-r from-amber-400 to-rose-400 px-4 py-2.5 text-sm font-semibold text-background transition-opacity disabled:opacity-50"
              >
                {lbusy ? "Logging in…" : "Login"}
              </button>
            </form>
          </div>

          <div className="flex items-center gap-3 text-xs uppercase tracking-widest text-muted-foreground">
            <span aria-hidden className="h-px flex-1 bg-border" />
            or
            <span aria-hidden className="h-px flex-1 bg-border" />
          </div>

          {/* or, tell us about yourself → creation form */}
          <div>
            <h2 className="text-xl font-semibold">
              or, tell us about yourself
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Your selections are saved with your new account so you only
              answer once.
            </p>

          {intake && (
            <div className="mt-4 rounded-lg border border-border bg-background/60 p-3 text-xs text-muted-foreground">
              <p>
                <span className="text-foreground">Origin:</span> {intake.origin}
              </p>
              {intake.destinations.length > 0 && (
                <p className="mt-1">
                  <span className="text-foreground">Destinations:</span>{" "}
                  {intake.destinations.join(", ")}
                </p>
              )}
              <p className="mt-1">
                <span className="text-foreground">Interests:</span>{" "}
                {pickedNames.join(", ")}
                {intake.interest_name
                  ? `${pickedNames.length ? ", " : ""}${intake.interest_name}`
                  : ""}
              </p>
              {intake.date_from && intake.date_to && (
                <p className="mt-1">
                  <span className="text-foreground">When:</span>{" "}
                  {intake.when_label || (
                    <>{intake.date_from} → {intake.date_to}</>
                  )}
                  {intake.when_label && (
                    <span className="text-muted-foreground">
                      {" "}({intake.date_from} → {intake.date_to})
                    </span>
                  )}
                </p>
              )}
            </div>
          )}

          <form onSubmit={submit} className="mt-6 space-y-4">
            <Field
              label="Full name"
              value={name}
              onChange={setName}
              required
            />
            <Field
              label="Email"
              type="email"
              value={email}
              onChange={setEmail}
              required
              autoComplete="email"
            />
            <Field
              label="Phone (optional)"
              value={phone}
              onChange={setPhone}
              type="tel"
              autoComplete="tel"
            />
            <Field
              label="Address (optional)"
              value={address}
              onChange={setAddress}
              autoComplete="street-address"
            />
            <Field
              label="Password (min 12 characters)"
              type="password"
              value={password}
              onChange={setPassword}
              required
              autoComplete="new-password"
            />
            <Field
              label="Where did you hear about us? (optional)"
              value={referrer}
              onChange={setReferrer}
            />

            <details className="rounded-md border border-border bg-background/40 p-3">
              <summary className="cursor-pointer text-sm font-medium">
                Travel documents (optional — needed for international booking)
              </summary>
              <p className="mt-2 text-xs text-muted-foreground">
                Add these now if you want a booking agent to handle the trip.
                Skip for now; you can add them later from your profile.
              </p>
              <div className="mt-3 space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <Field
                    label="Nationality (ISO code)"
                    value={nationality}
                    onChange={setNationality}
                    placeholder="MZ"
                    autoComplete="country"
                    maxLength={2}
                  />
                  <Field
                    label="Date of birth"
                    type="date"
                    value={dateOfBirth}
                    onChange={setDateOfBirth}
                    autoComplete="bday"
                  />
                </div>
                <div className="grid grid-cols-3 gap-3">
                  <Field
                    label="Passport number"
                    value={passportNumber}
                    onChange={setPassportNumber}
                    autoComplete="off"
                  />
                  <Field
                    label="Passport expiry"
                    type="date"
                    value={passportExpiry}
                    onChange={setPassportExpiry}
                  />
                  <Field
                    label="Issuing country (ISO)"
                    value={passportIssuingCountry}
                    onChange={setPassportIssuingCountry}
                    placeholder="MZ"
                    maxLength={2}
                  />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <Field
                    label="Emergency contact name"
                    value={emergencyContactName}
                    onChange={setEmergencyContactName}
                    autoComplete="name"
                  />
                  <Field
                    label="Emergency contact phone"
                    type="tel"
                    value={emergencyContactPhone}
                    onChange={setEmergencyContactPhone}
                    autoComplete="tel"
                  />
                </div>
              </div>
            </details>

            {err && (
              <p className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-300">
                {err}
              </p>
            )}

            <button
              type="submit"
              disabled={busy || !intake}
              className="w-full rounded-lg bg-gradient-to-r from-amber-400 to-rose-400 px-4 py-3 text-base font-semibold text-background transition-opacity disabled:opacity-50"
            >
              {busy ? "Creating account…" : "Create my account & save this trip"}
            </button>

            <p className="text-center text-xs text-muted-foreground">
              By creating an account you agree we&apos;ll store your interests
              and intake answers to personalise your trips.
            </p>
          </form>
          </div>
        </div>
      </section>
      )}
    </main>
  );
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  required = false,
  autoComplete,
  placeholder,
  maxLength,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  required?: boolean;
  autoComplete?: string;
  placeholder?: string;
  maxLength?: number;
}) {
  const id = `field-${label.replace(/[^a-z0-9]/gi, "-").toLowerCase()}`;
  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium">
        {label}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required={required}
        autoComplete={autoComplete}
        placeholder={placeholder}
        maxLength={maxLength}
        className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:border-primary focus:outline-none"
      />
    </div>
  );
}

export default function OnboardingPage() {
  return (
    <Suspense fallback={<p className="p-8 text-muted-foreground">Loading…</p>}>
      <OnboardingInner />
    </Suspense>
  );
}
