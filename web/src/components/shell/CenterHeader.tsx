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
    <header className="sticky top-0 z-10 border-b border-border bg-background">
      <div className="flex justify-center pt-4">
        <div role="tablist" aria-label="Views" className="flex gap-1 rounded-[11px] border border-border bg-muted p-1">
          {TABS.map((t) => {
            const reason = enabled(t.id);
            const active = t.id === tab;
            const cls = cn(
              "inline-flex h-9 items-center rounded-md px-5 text-[14px]",
              active ? "border border-border-strong bg-card text-foreground dark:bg-secondary" : "text-muted-foreground",
              reason ? "cursor-default opacity-60" : "hover:text-foreground",
            );
            return reason ? (
              <span key={t.id} role="tab" aria-selected={active} aria-disabled title={reason} className={cls}>{t.label}</span>
            ) : (
              <Link key={t.id} role="tab" aria-selected={active} to={`/d/${dataset.id}/${t.id}`} className={cls}>{t.label}</Link>
            );
          })}
        </div>
      </div>
      <div className="flex min-h-14 items-center gap-3 px-6 py-3">
        <h1 className="truncate text-[15px] font-semibold">{dataset.name}</h1>
        {dataset.current_version > 0 && (
          <span className="rounded-full bg-muted px-2.5 py-0.5 font-mono text-[12.5px] text-muted-foreground">
            v{dataset.current_version}
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">{actions}</div>
      </div>
    </header>
  );
}
