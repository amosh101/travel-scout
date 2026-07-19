"use client";

import { useCallback, useEffect, useState } from "react";
import { apiFetch, ApiError } from "../../../lib/api";

type SourceRow = {
  kind: "event" | "flight";
  key: string;
  name: string;
  base_url: string;
  auth_env_var: string | null;
  enabled: boolean;
};

export default function AdminSourcesPage() {
  const [items, setItems] = useState<SourceRow[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await apiFetch<{ items: SourceRow[] }>("/api/admin/sources");
      setItems(data.items);
      setErr(null);
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Failed to load sources (${e.status})`
          : e instanceof Error
            ? e.message
            : "Failed to load sources"
      );
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const toggle = async (s: SourceRow) => {
    const k = `${s.kind}/${s.key}`;
    setBusy(k);
    try {
      await apiFetch(`/api/admin/sources/${s.kind}/${s.key}`, {
        method: "PATCH",
        body: { enabled: !s.enabled },
      });
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Toggle failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold">Data sources</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          External APIs that feed the discover algorithm. Disabling a source
          means the algorithm won&apos;t query it; it will fall back to whatever
          the remaining sources provide.
        </p>
      </div>

      {err && (
        <div className="rounded-lg border border-rose-300 bg-rose-50 p-3 text-sm text-rose-900 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-200">
          {err}
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-border bg-card">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="px-4 py-2">Kind</th>
              <th className="px-4 py-2">Name</th>
              <th className="px-4 py-2">Base URL</th>
              <th className="px-4 py-2">Auth env</th>
              <th className="px-4 py-2">Enabled</th>
            </tr>
          </thead>
          <tbody>
            {items === null ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">
                  Loading…
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-muted-foreground">
                  No sources configured.
                </td>
              </tr>
            ) : (
              items.map((s) => (
                <tr key={`${s.kind}/${s.key}`} className="border-t border-border">
                  <td className="px-4 py-2 font-mono text-xs">{s.kind}</td>
                  <td className="px-4 py-2">
                    {s.name}
                    <div className="font-mono text-[10px] text-muted-foreground">
                      {s.key}
                    </div>
                  </td>
                  <td className="px-4 py-2 font-mono text-xs text-muted-foreground">
                    {s.base_url}
                  </td>
                  <td className="px-4 py-2 font-mono text-xs text-muted-foreground">
                    {s.auth_env_var ?? "—"}
                  </td>
                  <td className="px-4 py-2">
                    <button
                      onClick={() => toggle(s)}
                      disabled={busy === `${s.kind}/${s.key}`}
                      className={`relative inline-flex h-6 w-11 items-center rounded-full transition disabled:opacity-50 ${
                        s.enabled ? "bg-emerald-500" : "bg-muted"
                      }`}
                      title={s.enabled ? "Disable" : "Enable"}
                    >
                      <span
                        className={`inline-block h-4 w-4 transform rounded-full bg-white transition ${
                          s.enabled ? "translate-x-6" : "translate-x-1"
                        }`}
                      />
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
