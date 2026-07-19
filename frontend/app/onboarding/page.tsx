"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { apiFetch, ApiError } from "../../lib/api";
import { useAuth } from "../../lib/auth-context";

type Interest = { key: string; name: string };

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
      {/* Step 1: working-on-it loading state */}
      <section className="container max-w-4xl pt-16 pb-10">
        <div className="text-center">
          <div className="mx-auto inline-flex h-12 w-12 animate-spin items-center justify-center rounded-full border-2 border-amber-400/30 border-t-amber-400" />
          <h1 className="mt-6 text-3xl font-semibold tracking-tight sm:text-4xl">
            Working on your best itineraries
          </h1>
          <p className="mt-3 text-muted-foreground">
            Cross-referencing real events, public holidays, race dates, and
            venues across your interests.
          </p>
        </div>

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
      </section>

      {/* Step 2: registration form */}
      <section className="container max-w-2xl pb-20">
        <div className="rounded-2xl border border-border bg-card p-6 shadow-xl sm:p-8">
          <h2 className="text-xl font-semibold">Tell us about yourself</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Your selections are saved with your account so you only answer
            once.
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
              {busy ? "Creating account…" : "Create my account & see trips"}
            </button>

            <p className="text-center text-xs text-muted-foreground">
              By creating an account you agree we&rsquo;ll store your interests
              and intake answers to personalise your trips.
            </p>
          </form>
        </div>
      </section>
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
