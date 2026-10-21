"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { apiFetch, ApiError } from "./api";

export type MeUser = {
  id: string;
  email: string;
  name: string;
  tier: string;
  permissions: string[];
};

type AuthState = {
  token: string | null;
  /** The real /api/auth/me payload when a live session exists. */
  user: MeUser | null;
  /** True once the user record resolved (or the session proved dead). */
  userReady: boolean;
  setToken: (t: string | null) => void;
  ready: boolean;
};

const AuthContext = createContext<AuthState | null>(null);

const TOKEN_KEY = "travel_scout_token";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [token, setTokenState] = useState<string | null>(null);
  const [user, setUser] = useState<MeUser | null>(null);
  const [userReady, setUserReady] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    try {
      const t = window.localStorage.getItem(TOKEN_KEY);
      if (t) setTokenState(t);
    } catch {
      // localStorage blocked — treat as logged out
    }
    setReady(true);
  }, []);

  const setToken = useCallback((t: string | null) => {
    setTokenState(t);
    setUser(null);
    setUserReady(t ? false : true);
    try {
      if (t) window.localStorage.setItem(TOKEN_KEY, t);
      else window.localStorage.removeItem(TOKEN_KEY);
    } catch {
      // ignore
    }
  }, []);

  // Resolve the real user whenever a token exists. A 401 means the
  // session is dead: drop the token so the whole app returns to the
  // signed-out state instead of limping on a stale credential.
  useEffect(() => {
    if (!token) {
      setUser(null);
      setUserReady(true);
      return;
    }
    let cancelled = false;
    setUserReady(false);
    (async () => {
      try {
        const v = await apiFetch<MeUser>("/api/auth/me");
        if (cancelled) return;
        setUser(v);
        setUserReady(true);
      } catch (e) {
        if (cancelled) return;
        setUser(null);
        setUserReady(true);
        if (e instanceof ApiError && e.status === 401) {
          try {
            window.localStorage.removeItem(TOKEN_KEY);
          } catch {
            // ignore
          }
          setTokenState(null);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token]);

  const value = useMemo(
    () => ({ token, user, setToken, ready, userReady }),
    [token, user, setToken, ready, userReady],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used inside <AuthProvider>");
  }
  return ctx as AuthState;
}