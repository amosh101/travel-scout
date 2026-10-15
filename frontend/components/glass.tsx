"use client";
import { forwardRef } from "react";
import { cn } from "@/lib/utils";

/**
 * LiquidGlass — the frosted material used for all surface content
 * on top of a contextual backdrop.
 *
 * Mechanics:
 *   - backdrop-filter: blur + saturate
 *   - semi-transparent white background
 *   - 1px white border with subtle inner highlight (top)
 *   - soft shadow + accent halo (theme-aware)
 *
 * Variants:
 *   - default: standard frosted card
 *   - strong:  more opaque, used for hero/forms on busy backdrops
 *   - subtle:  lighter frosted, used for inline pills/badges
 *   - bold:    highest prominence, for results + CTAs
 */
type Variant = "default" | "strong" | "subtle" | "bold";

type GlassCardProps = React.HTMLAttributes<HTMLDivElement> & {
  variant?: Variant;
  accent?: string;
};

export const GlassCard = forwardRef<HTMLDivElement, GlassCardProps>(
  function GlassCard({ variant = "default", accent = "#ffffff", className, style, children, ...rest }, ref) {
    const baseRadius = "rounded-2xl";

    const backdropLevel =
      variant === "bold" ? "backdrop-blur-2xl backdrop-saturate-200"
      : variant === "strong" ? "backdrop-blur-2xl backdrop-saturate-150"
      : variant === "subtle" ? "backdrop-blur-md backdrop-saturate-150"
      : "backdrop-blur-xl backdrop-saturate-150";

    const opacity =
      variant === "bold" ? "bg-white/[0.22] dark:bg-white/[0.15]"
      : variant === "strong" ? "bg-white/[0.18] dark:bg-white/[0.12]"
      : variant === "subtle" ? "bg-white/[0.06] dark:bg-white/[0.04]"
      : "bg-white/10 dark:bg-white/[0.08]";

    const border =
      variant === "bold" ? "border-white/30"
      : variant === "strong" ? "border-white/20"
      : variant === "subtle" ? "border-white/10"
      : "border-white/15";

    const styleWithAccent: React.CSSProperties = {
      ...(style ?? {}),
      borderTopColor: `${accent}40`,
      WebkitBackdropFilter: "blur(20px) saturate(160%)",
    };

    return (
      <div
        ref={ref}
        className={cn(baseRadius, backdropLevel, opacity, "border", border, "relative", className)}
        style={styleWithAccent}
        {...rest}
      >
        {/* Inner top highlight for the "glass" feel */}
        <span
          aria-hidden
          className="pointer-events-none absolute inset-x-2 top-0 h-px"
          style={{
            background: `linear-gradient(90deg, transparent, ${accent}59 50%, transparent)`,
          }}
        />
        {children}
      </div>
    );
  },
);

/** Pill/badge that sits on top of frosted surfaces. */
export function GlassPill({
  className,
  children,
  accent,
  ...rest
}: { accent?: string } & React.HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      {...rest}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border border-white/20 bg-white/[0.12] px-3 py-1 text-xs font-medium backdrop-blur dark:bg-white/[0.08]",
        className,
      )}
      style={{ borderColor: `${accent ?? "#ffffff"}40` }}
    >
      {children}
    </span>
  );
}
