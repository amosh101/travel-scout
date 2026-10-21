"use client";

import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/lib/auth-context";

const _PILL =
  "inline-flex items-center rounded-full border border-white/30 bg-white/10 px-3.5 py-1.5 text-sm font-medium text-white shadow-lg backdrop-blur transition hover:bg-white/20";

function _initials(name: string, email: string): string {
  const n = (name || "").trim();
  if (n) {
    const parts = n.split(/\s+/).slice(0, 2);
    return parts.map((p) => p[0]?.toUpperCase() ?? "").join("");
  }
  return (email || "?").slice(0, 2).toUpperCase();
}

/**
 * Global, role-aware auth bar: rendered in-flow by PageShell on every
 * page except the auth forms and the admin console (which carry their
 * own chrome).
 *
 * Sign-in status matrix (all read from the REAL /api/auth/me permissions
 * carried by the auth context — never the tier or a role-name string):
 *   anonymous              -> [Sign in]
 *   customer (signed in)   -> [My saved trips] [initials] [Sign out]
 *   booking agent          -> + [Agent console]  (agent.work / agent.assign)
 *   admin                  -> + [Admin]          (user.update / weights.update
 *                                                 / destination.admin / source.admin)
 *   dead session           -> treated as signed out (the context drops
 *                             the stale token on 401)
 */
export function AuthNav() {
  const { token, user, setToken, ready, userReady } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  // Hide on pages with their own chrome. AFTER the hooks (rules of hooks).
  const hide =
    !pathname || pathname.startsWith("/auth") || pathname.startsWith("/admin");
  if (hide || !ready) {
    return null;
  }

  const signedOutLike = !token || (userReady && !user);

  if (signedOutLike) {
    return (
      <header className="relative z-30 flex h-12 items-center justify-between px-4 sm:px-6">
        <Link
          href="/"
          className="text-sm font-semibold tracking-tight text-white drop-shadow"
        >
          Travel Scout
        </Link>
        <Link href="/auth/login" className={_PILL}>
          Sign in
        </Link>
      </header>
    );
  }

  const perms = new Set(user?.permissions ?? []);
  const isAdmin = ["user.update", "weights.update", "destination.admin", "source.admin"].some((p) => perms.has(p));
  const isAgent = ["agent.work", "agent.assign"].some((p) => perms.has(p));

  return (
    <header className="relative z-30 flex h-12 items-center justify-between px-4 sm:px-6">
      <Link
        href="/"
        className="text-sm font-semibold tracking-tight text-white drop-shadow"
      >
        Travel Scout
      </Link>
      <div className="flex flex-wrap items-center justify-end gap-2">
        <Link href="/itineraries" className={_PILL}>
          My saved trips
        </Link>
        {isAgent && (
          <Link href="/admin/queue" className={_PILL}>
            Agent console
          </Link>
        )}
        {isAdmin && (
          <Link href="/admin" className={_PILL}>
            Admin
          </Link>
        )}
        {user && (
          <span
            className="hidden cursor-default rounded-full border border-white/20 bg-white/[0.08] px-3 py-1.5 text-xs font-medium text-white/90 backdrop-blur sm:inline-flex"
            title={user.email}
          >
            {_initials(user.name, user.email)}
          </span>
        )}
        <button
          type="button"
          onClick={() => {
            setToken(null);
            router.push("/");
          }}
          className={_PILL}
        >
          Sign out
        </button>
      </div>
    </header>
  );
}