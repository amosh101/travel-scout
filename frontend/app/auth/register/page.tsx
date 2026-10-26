"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { apiFetch, ApiError } from "../../../lib/api";
import { useAuth } from "../../../lib/auth-context";

function RegisterForm() {
  const router = useRouter();
  const sp = useSearchParams();
  const { token, setToken } = useAuth();
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  // Landing-page intake handoff: /auth/register?next=…&intent=<id>. The
  // selections the visitor picked on the home page attach to the NEW account
  // at registration (backend consumes the intent one-time). Intents live in
  // Redis for 1 hour — a stale one must NOT block signup, hence the 410
  // retry below without it.
  const intent = sp?.get("intent") ?? "";

  // Already signed in: the form is redundant — say so and move on.
  // (On /auth/* the global AuthNav is hidden, so this page carries its
  // own affordances.)
  if (token) {
    return (
      <div className="w-full max-w-sm space-y-6 rounded-lg border border-border bg-card p-6">
        <h1 className="text-2xl font-semibold">Already signed in</h1>
        <p className="text-sm text-muted-foreground">
          You have an active session. Head to your trips, or sign out below.
        </p>
        <Link
          href="/saved"
          className="w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground text-center"
        >
          Open my saved trips
        </Link>
        <button
          type="button"
          onClick={() => setToken(null)}
          className="w-full rounded-md border border-border px-4 py-2 text-sm font-medium"
        >
          Sign out
        </button>
      </div>
    );
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    setNote(null);
    const attempt = (withIntake: boolean) =>
      apiFetch<{
        access_token: string;
        user: { id: string; email: string };
      }>("/api/auth/register", {
        method: "POST",
        body: {
          email,
          password,
          name,
          ...(withIntake && intent ? { intake_id: intent } : {}),
        },
      });
    let res: { access_token: string; user: { id: string; email: string } };
    try {
      try {
        res = await attempt(true);
      } catch (e) {
        // The intake lives only 1 hour (Redis). A 410 means it expired —
        // the backend rejects BEFORE creating any user row, so retrying
        // without the intake is safe and signup still succeeds.
        if (!(e instanceof ApiError) || e.status !== 410 || !intent) throw e;
        setNote(
          "Your search selections expired before signup, so they weren't attached to this account — redo your search on the home page anytime.",
        );
        res = await attempt(false);
      }
      setToken(res.access_token);
      // Honour ?next= so the user lands back where they were. Only
      // accept same-origin paths to prevent open-redirect abuse.
      const next = sp?.get("next");
      const safeNext =
        next && next.startsWith("/") && !next.startsWith("//") ? next : "/saved";
      router.push(safeNext);
    } catch (e) {
      const msg =
        e instanceof ApiError
          ? e.status === 409
            ? "Email already registered"
            : e.status === 422
              ? "Password must be at least 12 characters"
              : `Error ${e.status}`
          : e instanceof Error
            ? e.message
            : "Registration failed";
      setErr(msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="w-full max-w-sm space-y-6 rounded-lg border border-border bg-card p-6">
      <h1 className="text-2xl font-semibold">Create account</h1>

      <form onSubmit={submit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium" htmlFor="name">
            Name
          </label>
          <input
            id="name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
            autoComplete="name"
          />
        </div>
        <div>
          <label className="block text-sm font-medium" htmlFor="email">
            Email
          </label>
          <input
            id="email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
            autoComplete="email"
          />
        </div>
        <div>
          <label className="block text-sm font-medium" htmlFor="password">
            Password (min 12 chars)
          </label>
          <input
            id="password"
            type="password"
            required
            minLength={12}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
            autoComplete="new-password"
          />
        </div>
        {err && <p className="text-sm text-red-600">{err}</p>}
        {note && <p className="text-xs text-muted-foreground">{note}</p>}
        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
        >
          {busy ? "Creating…" : "Create account"}
        </button>
      </form>

      <p className="text-sm text-muted-foreground">
        Already have one?{" "}
        <Link href="/auth/login" className="text-primary underline">
          Sign in
        </Link>
        .
      </p>
    </div>
  );
}

export default function RegisterPage() {
  // useSearchParams() must be inside a Suspense boundary (Next.js 15
  // requirement) — wrapping the form lets the static shell render
  // while the params resolve.
  return (
    <Suspense fallback={<div className="p-8 text-muted-foreground">Loading…</div>}>
      <RegisterForm />
    </Suspense>
  );
}
