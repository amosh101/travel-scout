"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, ApiError } from "../../../lib/api";

type WeightRow = {
  key: string;
  value: string;
  description: string;
  updated_at: string;
  updated_by: string | null;
};

export default function AdminWeightsPage() {
  const [items, setItems] = useState<WeightRow[] | null>(null);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await apiFetch<{ items: WeightRow[] }>("/api/admin/weights");
      setItems(data.items);
      setErr(null);
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Failed to load weights (${e.status})`
          : e instanceof Error
            ? e.message
            : "Failed to load weights"
      );
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const save = async (key: string) => {
    const newVal = edits[key];
    if (newVal === undefined) return;
    setBusy(key);
    setSaved(null);
    try {
      const w = items?.find((i) => i.key === key);
      await apiFetch(`/api/admin/weights/${key}`, {
        method: "PATCH",
        body: { value: newVal, description: w?.description },
      });
      await load();
      setSaved(key);
      setTimeout(() => setSaved(null), 2000);
      setEdits((p) => {
        const n = { ...p };
        delete n[key];
        return n;
      });
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold">Algorithm weights</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Scoring factors used by the discover algorithm. Changes take effect
          on the next discover call (the algorithm reads the current values
          per-request — no restart needed).
        </p>
      </div>

      {err && (
        <div className="rounded-lg border border-rose-300 bg-rose-50 p-3 text-sm text-rose-900 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-200">
          {err}
        </div>
      )}

      {saved && (
        <div className="rounded-lg border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200">
          Saved <code>{saved}</code>.
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-border bg-card">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-4 py-2">Key</th>
              <th className="px-4 py-2">Description</th>
              <th className="px-4 py-2">Current value</th>
              <th className="px-4 py-2">New value</th>
              <th className="px-4 py-2">Updated</th>
              <th className="px-4 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {items === null ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">
                  Loading…
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">
                  No weights configured.
                </td>
              </tr>
            ) : (
              items.map((w) => {
                const dirty = edits[w.key] !== undefined && edits[w.key] !== w.value;
                return (
                  <tr key={w.key} className="border-t border-border align-top">
                    <td className="px-4 py-2 font-mono text-xs">{w.key}</td>
                    <td className="px-4 py-2 text-muted-foreground">{w.description}</td>
                    <td className="px-4 py-2 font-mono">{w.value}</td>
                    <td className="px-4 py-2">
                      <input
                        value={edits[w.key] ?? w.value}
                        onChange={(e) =>
                          setEdits((p) => ({ ...p, [w.key]: e.target.value }))
                        }
                        className="w-24 rounded border border-border bg-background px-2 py-1 font-mono text-xs"
                      />
                    </td>
                    <td className="px-4 py-2 text-xs text-muted-foreground">
                      {new Date(w.updated_at).toLocaleString()}
                      {w.updated_by && (
                        <div className="font-mono text-[10px]">
                          {w.updated_by.slice(0, 8)}…
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-2">
                      <button
                        onClick={() => save(w.key)}
                        disabled={!dirty || busy === w.key}
                        className="rounded bg-foreground/10 px-3 py-1 text-xs font-medium transition hover:bg-foreground/20 disabled:opacity-30"
                      >
                        {busy === w.key ? "…" : "Save"}
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
