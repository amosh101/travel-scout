"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { apiFetch, ApiError } from "../../../lib/api";
import { useAuth } from "../../../lib/auth-context";

function LoginForm() {
  const router = useRouter();
  const sp = useSearchParams();
  const { setToken } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const res = await apiFetch<{
        access_token: string;
        user: { id: string; email: string };
      }>("/api/auth/login", {
        method: "POST",
        body: { email, password },
      });
      setToken(res.access_token);
      // Honour ?next= so the user lands back where they were (e.g. on
      // the itineraries page they were previewing before signup). Only
      // accept same-origin paths to prevent open-redirect abuse.
      const next = sp?.get("next");
      const safeNext =
        next && next.startsWith("/") && !next.startsWith("//") ? next : "/saved";
      router.push(safeNext);
    } catch (e) {
      const msg =
        e instanceof ApiError && e.status === 401
          ? "Invalid email or password"
          : e instanceof Error
            ? e.message
            : "Login failed";
      setErr(msg);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="w-full max-w-sm space-y-6 rounded-lg border border-border bg-card p-6">
      <h1 className="text-2xl font-semibold">Sign in</h1>

      <form onSubmit={submit} className="space-y-4">
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
            Password
          </label>
          <input
            id="password"
            type="password"
            required
            minLength={12}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
            autoComplete="current-password"
          />
        </div>
        {err && <p className="text-sm text-red-400">{err}</p>}
        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>

      <p className="text-sm text-muted-foreground">
        No account?{" "}
        <Link href="/auth/register" className="text-primary underline">
          Create one
        </Link>
        .
      </p>
    </div>
  );
}

export default function LoginPage() {
  // useSearchParams() must be inside a Suspense boundary (Next.js 15
  // requirement) — wrapping the form lets the static shell render
  // while the params resolve.
  return (
    <Suspense fallback={<div className="p-8 text-muted-foreground">Loading…</div>}>
      <LoginForm />
    </Suspense>
  );
}
