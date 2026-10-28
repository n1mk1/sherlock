// Segmented control: a soft pill track with the chosen option raised on it.
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Segmented<T extends string>({ label, value, options, onChange }: {
  label: string;
  value: T;
  options: { value: T; label: ReactNode }[];
  onChange: (v: T) => void;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex flex-wrap gap-0.5 rounded-full bg-secondary p-0.5">
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(o.value)}
            className={cn(
              "inline-flex h-8 items-center gap-1.5 rounded-full px-3.5 text-[13px] font-medium transition-[background-color,color] duration-[var(--duration-fast)]",
              "focus-visible:outline-2 focus-visible:outline-ring",
              active
                ? "bg-card text-foreground shadow-[0_1px_2px_rgba(0,0,0,0.08)] dark:bg-[color-mix(in_srgb,var(--foreground)_14%,transparent)]"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
