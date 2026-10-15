"use client";
import { cn } from "@/lib/utils";

/**
 * Multi-layer backdrop:
 *  - full-bleed backdrop image (procedural ambient, supplied by parent)
 *  - dark overlay (proportional) for text readability
 *  - subtle blur of the image (background-image, blur applied via filter)
 *  - color wash (CSS gradient using the theme palette) for theme-tinted atmosphere
 *
 * Children render in the foreground on top.
 *
 * Variants:
 *  - intensity="normal" (default): for hero/detail pages — image is
 *    prominent and overlay is subtle
 *  - intensity="subtle": for cards/secondary panels — heavy blur and
 *    stronger overlay, image is mood rather than focus
 */
export function BackgroundCanvas({
  src,
  palette,
  intensity = "normal",
  children,
  className,
}: {
  src: string;
  palette: { sky: string; horizon: string; sea: string; accent: string };
  intensity?: "normal" | "subtle" | "vivid";
  children?: React.ReactNode;
  className?: string;
}) {
  const isSubtle = intensity === "subtle";
  const isVivid = intensity === "vivid";

  return (
    <div className={cn("relative isolate min-h-screen overflow-hidden", className)}>
      {/* Layer 1: backdrop image */}
      <div
        aria-hidden
        className={cn(
          "pointer-events-none absolute inset-0 -z-30",
          isSubtle ? "scale-110 blur-2xl saturate-50" : isVivid ? "scale-105" : "scale-110",
        )}
        style={{
          backgroundImage: `url(${src})`,
          backgroundSize: "cover",
          backgroundPosition: "center",
          filter: isSubtle
            ? "blur(28px) saturate(0.6) brightness(0.7)"
            : isVivid
              ? "saturate(1.15) brightness(1.0)"
              : "saturate(1.05)",
        }}
      />
      {/* Layer 2: vertical gradient wash for legibility */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 -z-20"
        style={{
          background: `linear-gradient(180deg, ${palette.sky}26 0%, ${palette.horizon}40 38%, ${palette.sea}A6 100%)`,
        }}
      />
      {/* Layer 3: top vignette for content padding */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-64"
        style={{
          background: "linear-gradient(180deg, rgba(0,0,0,0.45), rgba(0,0,0,0))",
        }}
      />
      {/* Layer 4: bottom vignette */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 bottom-0 -z-10 h-48"
        style={{
          background: "linear-gradient(0deg, rgba(0,0,0,0.4), rgba(0,0,0,0))",
        }}
      />
      {/* Accent subtle radial at top right */}
      <div
        aria-hidden
        className="pointer-events-none absolute -right-32 -top-32 -z-10 h-96 w-96 rounded-full opacity-30 blur-3xl"
        style={{ background: palette.accent }}
      />
      <div className="relative z-0">{children}</div>
    </div>
  );
}
