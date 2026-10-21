"use client";

import { useEffect, useMemo } from "react";
import { usePathname } from "next/navigation";
import { useBackground } from "@/lib/background-store";
import { pickBackground, THEME_PALETTE_CSS } from "@/lib/backgrounds";
import { BackgroundCanvas } from "@/components/background-canvas";
import { AuthNav } from "@/components/auth-nav";

/**
 * Page shell.
 * - Reads the static <body> classes from the active pathname so SSR-style
 *   classes (page states) still flow through.
 * - Wraps children in <BackgroundCanvas> with the current theme.
 * - Pages can override the theme at any time via useBackground().set().
 *
 * The default theme (when no override is set) is computed from the URL:
 *   /                        -> default random pick (mediterranean/tropical/...)
 *   /itineraries?destination -> theme picked from destination's country
 *   /search?q=<city>         -> theme picked from searched city
 *   /saved                   -> old_world / wine (logged-in home) default
 *
 * This avoids making every page re-implement background wiring; they just
 * call useBackground().set() once with their picked background.
 */
const FALLBACK_ROTATION: import("@/lib/backgrounds").ThemeId[] = [
  "mediterranean",
  "tropical",
  "mountain",
  "old_world",
  "safari",
];

function defaultForPath(path: string, search: string): {
  theme: import("@/lib/backgrounds").ThemeId;
  variant: "a" | "b" | "c";
  src: string;
  palette: { sky: string; horizon: string; sea: string; accent: string };
} {
  // Pull destination from URL params
  const params = new URLSearchParams(search);
  const dest = params.get("destination");
  if (dest) {
    // Pass a generic country — destination string only. Pickers default
    // to "old_world" when no country is supplied.
    const picked = pickBackground({ city: dest });
    return { theme: picked.theme, variant: picked.variant, src: picked.src, palette: picked.palette };
  }
  // Default rotation based on URL hash so pages are stable.
  const hash = path.split("").reduce((acc, c) => acc + c.charCodeAt(0), 0);
  const theme = FALLBACK_ROTATION[hash % FALLBACK_ROTATION.length];
  const variant: "a" | "b" | "c" = ["a", "b", "c"][hash % 3] as "a" | "b" | "c";
  return {
    theme,
    variant,
    src: `/backgrounds/${theme}_${variant}.jpg`,
    palette: THEME_PALETTE_CSS[theme],
  };
}

export function PageShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  // Pull each slot individually from the store. Zustand uses Object.is
  // for equality, so individual primitive refs are stable across renders
  // and won't trigger spurious re-renders that would cascade into loops.
  const theme = useBackground((s) => s.theme);
  const variant = useBackground((s) => s.variant);
  const src = useBackground((s) => s.src);
  const palette = useBackground((s) => s.palette);
  const intensity = useBackground((s) => s.intensity);

  useEffect(() => {
    // Apply pathname-derived default on first mount or after route
    // change. If a deeper page has already set its own theme (e.g. the
    // itineraries page picking based on destination), we skip — the
    // override marker `__pageSet` tells us so.
    const search = typeof window !== "undefined" ? window.location.search : "";
    const state = useBackground.getState();
    if (state.overridden) {
      // Page took ownership — don't clobber. Reset the flag on unmount
      // so the next route gets a fresh default.
      const reset = state.reset;
      return () => {
        reset();
      };
    }
    const next = defaultForPath(pathname ?? "/", search);
    state.set({ ...next, intensity: "normal" });
    const reset = state.reset;
    return () => {
      reset();
    };
  }, [pathname]);

  const resolvedPalette = palette ?? THEME_PALETTE_CSS.mediterranean;
  const resolvedSrc = src ?? "/backgrounds/mediterranean_a.jpg";

  return (
    <BackgroundCanvas
      src={resolvedSrc}
      palette={resolvedPalette}
      intensity={intensity ?? "normal"}
    >
      <AuthNav />
      {children}
    </BackgroundCanvas>
  );
}
