"use client";

import { create } from "zustand";

/**
 * Auth store. The full session/token API lands in t3_user_journey; this
 * minimal shape lets the foundation app render without throwing.
 */

export type Role = "user" | "admin" | "agent" | "superadmin" | "support" | "finance" | "curator";

export interface SessionUser {
  id: string;
  email: string;
  name: string;
  tier: "free" | "limited" | "unlimited" | "concierge";
  roles: Role[];
}

interface AuthState {
  user: SessionUser | null;
  accessToken: string | null;
  setSession: (user: SessionUser, token: string) => void;
  clear: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  accessToken: null,
  setSession: (user, accessToken) => set({ user, accessToken }),
  clear: () => set({ user: null, accessToken: null }),
}));