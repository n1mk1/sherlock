// Pills: the small rounded tags for a status, a count or a kind ("Ready", "3 issues", "From chat").
// Each tone is one of the theme's hues on its own soft fill; neutral is for counts that carry no meaning.
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type Tone = "neutral" | "accent" | "violet" | "blue" | "teal" | "green" | "amber" | "red";

const TONES: Record<Tone, string> = {
  neutral: "bg-secondary text-[color-mix(in_srgb,var(--muted-foreground)_70%,var(--foreground))]",
  accent: "bg-accent-soft text-accent-ink",
  violet: "bg-violet-soft text-violet-ink",
  blue: "bg-blue-soft text-blue-ink",
  teal: "bg-teal-soft text-teal-ink",
  green: "bg-green-soft text-green-ink",
  amber: "bg-amber-soft text-amber-ink",
  red: "bg-red-soft text-red-ink",
};

export function Pill({ tone = "neutral", size = "md", icon, className, title, children }: {
  tone?: Tone; size?: "sm" | "md"; icon?: ReactNode; className?: string; title?: string; children: ReactNode;
}) {
  return (
    <span
      title={title}
      className={cn(
        "inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full font-medium tnum [&_svg]:size-3 [&_svg]:shrink-0",
        size === "sm" ? "h-5 px-2 text-[11px]" : "h-6 px-2.5 text-[12px]",
        TONES[tone],
        className,
      )}
    >
      {icon}
      {children}
    </span>
  );
}

/** A dot in a hue: the status mark in tight places (the collapsed library). */
export function Dot({ tone, className }: { tone: Tone; className?: string }) {
  const fill: Record<Tone, string> = {
    neutral: "bg-muted-foreground", accent: "bg-accent", violet: "bg-violet", blue: "bg-blue", teal: "bg-teal",
    green: "bg-green", amber: "bg-amber", red: "bg-red",
  };
  return <span aria-hidden className={cn("inline-block size-1.5 shrink-0 rounded-full", fill[tone], className)} />;
}
