// Centre header (UI brief §3.2): the context row (name, version and steps, actions).
import type { ReactNode } from "react";
import type { Dataset } from "@/api/types";

export function CenterHeader({ dataset, actions }: {
  dataset: Dataset;
  actions?: ReactNode; // right-aligned: the grid's Save, the job tray, the dataset menu
}) {
  return (
    <header className="sticky top-0 z-10 flex flex-col border-b border-border bg-background px-6 pt-3">
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
