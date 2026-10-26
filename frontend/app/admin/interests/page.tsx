"use client";

/**
 * Admin CRUD over the interest taxonomy (permission: destination.admin).
 * Deactivation hides a key from onboarding + discover without deleting
 * historical user rows. Every change writes an audited before/after and
 * the list shows how many users hold each key.
 */

import { useAuth } from "@/lib/auth-context";
import { useCallback, useEffect, useState } from "react";

type Interest = {
  key: string;
  name: string;
  kind: string | null;
  is_active: boolean;
  users_with_interest: number;
};

export default function AdminInterestsPage() {
  const { token, ready, user } = useAuth();
  const [items, setItems] = useState<Interest[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [newKey, setNewKey] = useState("");
  const [newName, setNewName] = useState("");
  const [newKind, setNewKind] = useState("");

  const canWrite = !!user?.permissions?.includes("destination.admin");

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const r = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/api/admin/interests?include_inactive=true`,
        { headers: { Authorization: `Bearer ${token}` } },
      );
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        setErr(j.detail ?? `HTTP ${r.status}`);
        return;
      }
      const j = await r.json();
      setItems(j.items);
      setErr(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "network error");
    }
  }, [token]);

  useEffect(() => {
    if (ready) load();
  }, [ready, load]);

  async function toggleActive(it: Interest) {
    setBusy(it.key);
    try {
      const r = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/api/admin/interests/${it.key}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({ is_active: !it.is_active }),
        },
      );
      if (!r.ok) {
        const j = await r.json().catch(() => ({}));
        setErr(j.detail ?? `HTTP ${r.status}`);
        return;
      }
      await load();
    } finally {
      setBusy(null);
    }
  }

  async function create() {
    if (!newKey.trim() || !newName.trim()) {
      setErr("key and name are required (key: lowercase-with-dashes)");
      return;
    }
    setBusy("new");
    try {
      const r = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/api/admin/interests`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({
            key: newKey.trim(),
            name: newName.trim(),
            kind: newKind.trim() || null,
          }),
        },
      );
      const j = await r.json().catch(() => ({}));
      if (r.status === 201) {
        setNewKey("");
        setNewName("");
        setNewKind("");
        setErr(j.note ?? null);
        await load();
      } else {
        setErr(j.detail ?? `HTTP ${r.status}`);
      }
    } finally {
      setBusy(null);
    }
  }

  if (!ready) return <p className="p-8 text-sm text-muted-foreground">Loading…</p>;
  if (!canWrite)
    return (
      <p className="p-8 text-sm text-muted-foreground">
        Your role cannot edit the interest catalog (needs destination.admin).
      </p>
    );

  return (
    <div className="flex-1 p-8">
      <h1 className="text-2xl font-semibold">Interest catalog</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        {items?.length ?? "…"} keys. Deactivating hides a key from onboarding and
        discovery; the change is auditable and reversible. Newly created keys
        have no event source yet — discovery reports them honestly until wired.
      </p>

      {err && (
        <div className="mt-4 max-w-2xl rounded-lg border border-amber-500/40 bg-amber-500/10 px-4 py-2 text-sm">
          {err}
        </div>
      )}

      <div className="mt-6 flex max-w-2xl flex-wrap items-center gap-2">
        <input
          value={newKey}
          onChange={(e) => setNewKey(e.target.value)}
          placeholder="key (e.g. theatre)"
          className="w-44 rounded border border-border bg-card px-3 py-2 text-sm"
        />
        <input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          placeholder="Display name"
          className="w-56 rounded border border-border bg-card px-3 py-2 text-sm"
        />
        <input
          value={newKind}
          onChange={(e) => setNewKind(e.target.value)}
          placeholder="kind (music/sport/…)"
          className="w-40 rounded border border-border bg-card px-3 py-2 text-sm"
        />
        <button
          onClick={create}
          disabled={busy !== null}
          className="rounded bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {busy === "new" ? "Creating…" : "Create interest"}
        </button>
      </div>

      <div className="mt-8 overflow-auto rounded-xl border border-border bg-card">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted-foreground">
              <th className="px-4 py-2 font-medium">Key</th>
              <th className="px-4 py-2 font-medium">Name</th>
              <th className="px-4 py-2 font-medium">Kind</th>
              <th className="px-4 py-2 font-medium">Users holding</th>
              <th className="px-4 py-2 font-medium">Active</th>
              <th className="px-4 py-2" />
            </tr>
          </thead>
          <tbody>
            {(items || []).map((it) => (
              <tr key={it.key} className="border-b border-border/40">
                <td className="px-4 py-2 font-mono text-xs">{it.key}</td>
                <td className="px-4 py-2">{it.name}</td>
                <td className="px-4 py-2 text-muted-foreground">{it.kind}</td>
                <td className="px-4 py-2 font-mono text-xs">{it.users_with_interest}</td>
                <td className="px-4 py-2">
                  <span
                    className={
                      it.is_active
                        ? "rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-200"
                        : "rounded-full bg-rose-100 px-2 py-0.5 text-xs text-rose-900 dark:bg-rose-900/40 dark:text-rose-200"
                    }
                  >
                    {it.is_active ? "active" : "off"}
                  </span>
                </td>
                <td className="px-4 py-2 text-right">
                  <button
                    onClick={() => toggleActive(it)}
                    disabled={busy !== null}
                    className="rounded border border-border px-2 py-1 text-xs hover:bg-accent disabled:opacity-50"
                  >
                    {busy === it.key ? "…" : it.is_active ? "Deactivate" : "Activate"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}