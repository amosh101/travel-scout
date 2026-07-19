"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { apiFetch, ApiError } from "../../../lib/api";

type UserSummary = {
  id: string;
  email: string;
  name: string;
  is_active: boolean;
  tier: string;
  roles: string[];
  created_at: string;
};

type UsersList = {
  total: number;
  limit: number;
  offset: number;
  items: UserSummary[];
};

const PAGE_SIZE = 50;

export default function AdminUsersPage() {
  const router = useRouter();
  const params = useSearchParams();
  const [data, setData] = useState<UsersList | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [q, setQ] = useState(params.get("q") ?? "");
  const [tier, setTier] = useState<string>(params.get("tier") ?? "");
  const [isActive, setIsActive] = useState<string>(params.get("is_active") ?? "");
  const [roleKey, setRoleKey] = useState<string>(params.get("role_key") ?? "");
  const [offset, setOffset] = useState<number>(Number(params.get("offset") ?? 0));
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setErr(null);
    try {
      const sp = new URLSearchParams();
      if (q) sp.set("q", q);
      if (tier) sp.set("tier", tier);
      if (isActive) sp.set("is_active", isActive);
      if (roleKey) sp.set("role_key", roleKey);
      sp.set("limit", String(PAGE_SIZE));
      sp.set("offset", String(offset));
      const result = await apiFetch<UsersList>(`/api/admin/users?${sp.toString()}`);
      setData(result);
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Failed to load users (${e.status})`
          : e instanceof Error
            ? e.message
            : "Failed to load users"
      );
    } finally {
      setLoading(false);
    }
  }, [q, tier, isActive, roleKey, offset]);

  useEffect(() => {
    load();
  }, [load]);

  const applyFilters = () => {
    setOffset(0);
    const sp = new URLSearchParams();
    if (q) sp.set("q", q);
    if (tier) sp.set("tier", tier);
    if (isActive) sp.set("is_active", isActive);
    if (roleKey) sp.set("role_key", roleKey);
    router.replace(`/admin/users?${sp.toString()}`);
    // load() will trigger via state change
  };

  const total = data?.total ?? 0;
  const items = data?.items ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-3xl font-semibold">Users</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {total.toLocaleString()} total
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-3 rounded-xl border border-border bg-card p-4">
        <label className="flex flex-col text-xs text-muted-foreground">
          Search
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && applyFilters()}
            placeholder="email or name"
            className="mt-1 w-64 rounded border border-border bg-background px-2 py-1 text-sm"
          />
        </label>
        <label className="flex flex-col text-xs text-muted-foreground">
          Tier
          <select
            value={tier}
            onChange={(e) => setTier(e.target.value)}
            className="mt-1 rounded border border-border bg-background px-2 py-1 text-sm"
          >
            <option value="">All</option>
            <option value="free">Free</option>
            <option value="concierge">Concierge</option>
            <option value="admin_internal">Admin internal</option>
          </select>
        </label>
        <label className="flex flex-col text-xs text-muted-foreground">
          Status
          <select
            value={isActive}
            onChange={(e) => setIsActive(e.target.value)}
            className="mt-1 rounded border border-border bg-background px-2 py-1 text-sm"
          >
            <option value="">All</option>
            <option value="true">Active</option>
            <option value="false">Blocked</option>
          </select>
        </label>
        <label className="flex flex-col text-xs text-muted-foreground">
          Role
          <select
            value={roleKey}
            onChange={(e) => setRoleKey(e.target.value)}
            className="mt-1 rounded border border-border bg-background px-2 py-1 text-sm"
          >
            <option value="">Any</option>
            <option value="superadmin">superadmin</option>
            <option value="admin">admin</option>
            <option value="curator">curator</option>
            <option value="agent">agent</option>
            <option value="support">support</option>
            <option value="finance">finance</option>
          </select>
        </label>
        <button
          onClick={applyFilters}
          className="rounded bg-foreground/10 px-3 py-1.5 text-sm font-medium transition hover:bg-foreground/20"
        >
          Apply
        </button>
        {(q || tier || isActive || roleKey) && (
          <button
            onClick={() => {
              setQ("");
              setTier("");
              setIsActive("");
              setRoleKey("");
              setOffset(0);
              router.replace("/admin/users");
            }}
            className="rounded border border-border bg-background px-3 py-1.5 text-sm transition hover:bg-muted"
          >
            Clear
          </button>
        )}
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
              <th className="px-4 py-2">Email</th>
              <th className="px-4 py-2">Name</th>
              <th className="px-4 py-2">Tier</th>
              <th className="px-4 py-2">Roles</th>
              <th className="px-4 py-2">Status</th>
              <th className="px-4 py-2">Created</th>
            </tr>
          </thead>
          <tbody>
            {loading && items.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">
                  Loading…
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">
                  No users match the current filters.
                </td>
              </tr>
            ) : (
              items.map((u) => (
                <tr
                  key={u.id}
                  className="cursor-pointer border-t border-border transition hover:bg-muted/30"
                  onClick={() => router.push(`/admin/users/${u.id}`)}
                >
                  <td className="px-4 py-2 font-mono text-xs">
                    <Link
                      href={`/admin/users/${u.id}`}
                      className="hover:underline"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {u.email}
                    </Link>
                  </td>
                  <td className="px-4 py-2">{u.name}</td>
                  <td className="px-4 py-2 text-muted-foreground">{u.tier}</td>
                  <td className="px-4 py-2">
                    <div className="flex flex-wrap gap-1">
                      {u.roles.length === 0 ? (
                        <span className="text-xs text-muted-foreground">—</span>
                      ) : (
                        u.roles.map((r) => (
                          <span
                            key={r}
                            className="rounded-full bg-foreground/10 px-2 py-0.5 text-xs"
                          >
                            {r}
                          </span>
                        ))
                      )}
                    </div>
                  </td>
                  <td className="px-4 py-2">
                    {u.is_active ? (
                      <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-900 dark:bg-emerald-900/40 dark:text-emerald-200">
                        active
                      </span>
                    ) : (
                      <span className="rounded-full bg-rose-100 px-2 py-0.5 text-xs text-rose-900 dark:bg-rose-900/40 dark:text-rose-200">
                        blocked
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-2 text-xs text-muted-foreground">
                    {new Date(u.created_at).toLocaleDateString()}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between text-sm">
          <span className="text-muted-foreground">
            Showing {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
          </span>
          <div className="flex gap-2">
            <button
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              className="rounded border border-border bg-card px-3 py-1 disabled:opacity-50"
            >
              ← Previous
            </button>
            <button
              disabled={offset + PAGE_SIZE >= total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
              className="rounded border border-border bg-card px-3 py-1 disabled:opacity-50"
            >
              Next →
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
