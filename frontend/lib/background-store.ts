"use client";

import { create } from "zustand";

/**
 * Per-page background override. Pages set this on mount; the layout's
 * BackgroundCanvas reads it and switches theme without a full re-render
 * of children. Defensive: if a page forgets to set, we render the
 * pathname-based default.
 *
 * Why zustand (vs context): avoids context-API plumbing; we already
 * use it for auth.
 */

import type { ThemeId, Variant } from "./backgrounds";

type Palette = { sky: string; horizon: string; sea: string; accent: string };

type BgState = {
  theme: ThemeId | null;
  variant: Variant | null;
  src: string | null;
  palette: Palette | null;
  intensity: "normal" | "subtle" | "vivid";
  /**
   * Marker that a child page explicitly called `claim()` to take
   * ownership of the backdrop for the current route. PageShell checks
   * this before applying the pathname default — pages that want a
   * specific theme call claim() instead of set(), so PageShell knows
   * not to clobber their choice.
   */
  overridden: boolean;
  set: (next: {
    theme: ThemeId;
    variant: Variant;
    src: string;
    palette: Palette;
    intensity?: BgState["intensity"];
    override?: boolean;
  }) => void;
  claim: () => void;
  reset: () => void;
};

const DEFAULT_PALETTE: Palette = { sky: "#ffdeb2", horizon: "#e4a882", sea: "#60a2bc", accent: "#fcb864" };

export const useBackground = create<BgState>((set) => ({
  theme: null,
  variant: null,
  src: null,
  palette: null,
  intensity: "normal",
  overridden: false,
  set: (n) =>
    set({
      theme: n.theme,
      variant: n.variant,
      src: n.src,
      palette: n.palette ?? DEFAULT_PALETTE,
      intensity: n.intensity ?? "normal",
      overridden: n.override ?? false,
    }),
  claim: () => set({ overridden: true }),
  reset: () =>
    set({
      theme: null,
      variant: null,
      src: null,
      palette: null,
      intensity: "normal",
      overridden: false,
    }),
}));
