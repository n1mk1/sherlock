// Centre header: the file's name with one pill for where it stands (its saved changes once it's ready,
// else its status), and the actions on the right.
import type { ReactNode } from "react";
import type { Dataset } from "@/api/types";
import { displayName, statusOf } from "@/components/library/LibraryPanel";
import { Pill } from "@/components/ui/pill";

export function CenterHeader({ dataset, actions }: {
  dataset: Dataset;
  actions?: ReactNode; // right-aligned: the grid's Save, the job tray, the dataset menu
}) {
  const status = statusOf(dataset, Math.round(dataset.cleaning_progress?.pct ?? 0));
  const steps = dataset.step_count;
  return (
    <header className="sticky top-0 z-10 flex h-14 shrink-0 items-center gap-3 border-b border-border bg-card pl-6 pr-3 max-lg:pl-14">
      <h1 className="min-w-0 truncate text-[15px] font-semibold tracking-[-0.015em]" title={dataset.name}>{displayName(dataset.name)}</h1>
      {dataset.status !== "ready" ? (
        <Pill tone={status.tone} size="sm">{status.label}</Pill>
      ) : steps > 0 ? (
        <Pill tone="teal" size="sm">{steps} {steps === 1 ? "change" : "changes"}</Pill>
      ) : null}
      <div className="ml-auto flex items-center gap-1.5 max-lg:mr-10">{actions}</div>
    </header>
  );
}
