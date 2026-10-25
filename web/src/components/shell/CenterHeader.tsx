// Centre header (UI brief §3.2): the tab switcher, then the context row (name, version, actions).
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { Dataset, Tab } from "@/api/types";
import { cn } from "@/lib/utils";

const TABS: { id: Tab; label: string }[] = [
  { id: "csv", label: "CSV" },
  { id: "dashboard", label: "Dashboard" },
  { id: "flow", label: "Flow" },
];

export function CenterHeader({ dataset, tab, enabled, actions }: {
  dataset: Dataset;
  tab: Tab;
  enabled: (t: Tab) => string | null; // null = enabled, else the reason it isn't
  actions?: ReactNode;
}) {
  return (
    <header className="sticky top-0 z-10 flex flex-col gap-3 border-b border-border bg-background px-6 pt-3">
      <div className="flex justify-center">
        <div role="tablist" aria-label="Views" className="flex gap-1 rounded-[11px] border border-border bg-muted p-1">
          {TABS.map((t) => {
            const reason = enabled(t.id);
            const active = t.id === tab;
            const cls = cn(
              "inline-flex h-9 items-center rounded-md border px-[18px] text-[14px]",
              active ? "border-border-strong bg-card font-medium text-foreground dark:bg-secondary" : "border-transparent text-muted-foreground",
              reason ? "cursor-default opacity-40" : "hover:text-foreground",
            );
            return reason ? (
              <span key={t.id} role="tab" aria-selected={active} aria-disabled title={reason} className={cls}>{t.label}</span>
            ) : (
              <Link key={t.id} role="tab" aria-selected={active} to={`/d/${dataset.id}/${t.id}`} className={cls}>{t.label}</Link>
            );
          })}
        </div>
      </div>
      <div className="flex min-h-11 flex-wrap items-center gap-2.5 pb-3">
        <h1 className="truncate text-[15px] font-semibold">{dataset.name}</h1>
        {dataset.current_version > 0 && (
          <span className="inline-flex h-6 items-center rounded-full bg-muted px-2 font-mono text-[12px] text-muted-foreground">
            v{dataset.current_version}
            {dataset.step_count > 0 && ` · ${dataset.step_count} ${dataset.step_count === 1 ? "step" : "steps"}`}
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">{actions}</div>
      </div>
    </header>
  );
}
