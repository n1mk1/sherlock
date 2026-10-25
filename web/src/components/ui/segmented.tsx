// Segmented control (UI brief §4.12): settings and the tab switcher share its look.
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Segmented<T extends string>({ label, value, options, onChange }: {
  label: string;
  value: T;
  options: { value: T; label: ReactNode }[];
  onChange: (v: T) => void;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex flex-wrap gap-1 rounded-[11px] border border-border bg-muted p-1">
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
              "inline-flex h-9 items-center gap-1.5 rounded-md border px-3.5 text-[14px] focus-visible:outline-2 focus-visible:outline-ring",
              active
                ? "border-border-strong bg-card text-foreground dark:bg-secondary"
                : "border-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
