"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { apiFetch, ApiError } from "../../../../lib/api";

type UserDetail = {
  id: string;
  email: string;
  name: string;
  is_active: boolean;
  tier: string;
  roles: string[];
  created_at: string;
  updated_at: string;
  stripe_customer_id: string | null;
  interests_count: number;
  itineraries_count: number;
  subscription_status: string | null;
};

const ROLE_OPTIONS = [
  "superadmin",
  "admin",
  "curator",
  "agent",
  "support",
  "finance",
];

export default function AdminUserDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id ?? "";
  const [user, setUser] = useState<UserDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [nameEdit, setNameEdit] = useState("");
  const [tierEdit, setTierEdit] = useState("");
  const [activeEdit, setActiveEdit] = useState(true);
  const [newRole, setNewRole] = useState("");

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const data = await apiFetch<UserDetail>(`/api/admin/users/${id}`);
      setUser(data);
      setNameEdit(data.name);
      setTierEdit(data.tier);
      setActiveEdit(data.is_active);
      setErr(null);
    } catch (e) {
      setErr(
        e instanceof ApiError
          ? `Failed to load user (${e.status})`
          : e instanceof Error
            ? e.message
            : "Failed to load user"
      );
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const saveProfile = async () => {
    if (!user) return;
    setBusy("profile");
    try {
      await apiFetch(`/api/admin/users/${user.id}`, {
        method: "PATCH",
        body: {
          name: nameEdit !== user.name ? nameEdit : undefined,
          tier: tierEdit !== user.tier ? tierEdit : undefined,
          is_active: activeEdit !== user.is_active ? activeEdit : undefined,
        },
      });
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(null);
    }
  };

  const grantRole = async () => {
    if (!user || !newRole) return;
    setBusy(`grant-${newRole}`);
    try {
      await apiFetch(`/api/admin/users/${user.id}/roles`, {
        method: "POST",
        body: { role_key: newRole },
      });
      setNewRole("");
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Grant failed");
    } finally {
      setBusy(null);
    }
  };

  const revokeRole = async (roleKey: string) => {
    if (!user) return;
    if (!confirm(`Revoke role "${roleKey}" from ${user.email}?`)) return;
    setBusy(`revoke-${roleKey}`);
    try {
      await apiFetch(`/api/admin/users/${user.id}/roles/${roleKey}`, {
        method: "DELETE",
      });
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Revoke failed");
    } finally {
      setBusy(null);
    }
  };

  if (err && !user) {
    return (
      <div className="space-y-4">
        <Link href="/admin/users" className="text-sm text-muted-foreground hover:underline">
          ← Back to users
        </Link>
        <div className="rounded-lg border border-rose-300 bg-rose-50 p-4 text-sm text-rose-900">
          {err}
        </div>
      </div>
    );
  }
  if (!user) {
    return <div className="text-muted-foreground">Loading…</div>;
  }

  const grantableRoles = ROLE_OPTIONS.filter((r) => !user.roles.includes(r));

  return (
    <div className="space-y-8">
      <div>
        <Link
          href="/admin/users"
          className="text-sm text-muted-foreground hover:underline"
        >
          ← Back to users
        </Link>
        <h1 className="mt-2 text-3xl font-semibold">{user.name}</h1>
        <p className="font-mono text-sm text-muted-foreground">{user.email}</p>
      </div>

      {err && (
        <div className="rounded-lg border border-rose-300 bg-rose-50 p-3 text-sm text-rose-900 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-200">
          {err}
        </div>
      )}

      <section className="rounded-xl border border-border bg-card p-6">
        <h2 className="text-lg font-semibold">Profile</h2>
        <div className="mt-4 grid gap-4 md:grid-cols-3">
          <label className="flex flex-col text-sm">
            <span className="text-xs text-muted-foreground">Name</span>
            <input
              value={nameEdit}
              onChange={(e) => setNameEdit(e.target.value)}
              className="mt-1 rounded border border-border bg-background px-2 py-1"
            />
          </label>
          <label className="flex flex-col text-sm">
            <span className="text-xs text-muted-foreground">Tier</span>
            <select
              value={tierEdit}
              onChange={(e) => setTierEdit(e.target.value)}
              className="mt-1 rounded border border-border bg-background px-2 py-1"
            >
              <option value="free">free</option>
              <option value="concierge">concierge</option>
              <option value="admin_internal">admin_internal</option>
            </select>
          </label>
          <label className="flex items-end gap-2 text-sm">
            <input
              type="checkbox"
              checked={activeEdit}
              onChange={(e) => setActiveEdit(e.target.checked)}
              className="h-4 w-4"
            />
            <span>Active (unblock to allow sign-in)</span>
          </label>
        </div>
        <button
          onClick={saveProfile}
          disabled={busy === "profile"}
          className="mt-4 rounded bg-foreground/10 px-4 py-1.5 text-sm font-medium transition hover:bg-foreground/20 disabled:opacity-50"
        >
          {busy === "profile" ? "Saving…" : "Save profile"}
        </button>
      </section>

      <section className="rounded-xl border border-border bg-card p-6">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">Roles</h2>
          <span className="text-xs text-muted-foreground">
            {user.roles.length} active
          </span>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {user.roles.length === 0 ? (
            <span className="text-sm text-muted-foreground">No roles</span>
          ) : (
            user.roles.map((r) => (
              <span
                key={r}
                className="inline-flex items-center gap-1.5 rounded-full bg-foreground/10 px-3 py-1 text-sm"
              >
                {r}
                <button
                  onClick={() => revokeRole(r)}
                  disabled={busy === `revoke-${r}`}
                  className="text-rose-600 transition hover:text-rose-800 disabled:opacity-50"
                  title={`Revoke ${r}`}
                >
                  ×
                </button>
              </span>
            ))
          )}
        </div>
        {grantableRoles.length > 0 && (
          <div className="mt-6 flex items-end gap-2">
            <label className="flex flex-1 flex-col text-sm">
              <span className="text-xs text-muted-foreground">Grant role</span>
              <select
                value={newRole}
                onChange={(e) => setNewRole(e.target.value)}
                className="mt-1 rounded border border-border bg-background px-2 py-1"
              >
                <option value="">Choose…</option>
                {grantableRoles.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </label>
            <button
              onClick={grantRole}
              disabled={!newRole || busy === `grant-${newRole}`}
              className="rounded bg-foreground/10 px-4 py-1.5 text-sm font-medium transition hover:bg-foreground/20 disabled:opacity-50"
            >
              {busy === `grant-${newRole}` ? "Granting…" : "Grant"}
            </button>
          </div>
        )}
      </section>

      <section className="rounded-xl border border-border bg-card p-6">
        <h2 className="text-lg font-semibold">Account facts</h2>
        <dl className="mt-4 grid grid-cols-2 gap-x-8 gap-y-2 text-sm">
          <dt className="text-muted-foreground">User ID</dt>
          <dd className="font-mono text-xs">{user.id}</dd>
          <dt className="text-muted-foreground">Created</dt>
          <dd>{new Date(user.created_at).toLocaleString()}</dd>
          <dt className="text-muted-foreground">Updated</dt>
          <dd>{new Date(user.updated_at).toLocaleString()}</dd>
          <dt className="text-muted-foreground">Interests</dt>
          <dd>{user.interests_count}</dd>
          <dt className="text-muted-foreground">Itineraries saved</dt>
          <dd>{user.itineraries_count}</dd>
          <dt className="text-muted-foreground">Stripe customer</dt>
          <dd className="font-mono text-xs">
            {user.stripe_customer_id ?? "—"}
          </dd>
          <dt className="text-muted-foreground">Subscription status</dt>
          <dd>{user.subscription_status ?? "—"}</dd>
        </dl>
      </section>
    </div>
  );
}
