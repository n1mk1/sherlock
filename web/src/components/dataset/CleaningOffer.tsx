// The cleaning offer (App Flow §4, UI brief §5.3): what profiling found, in plain words: the counts and
// the three most severe issues. The full list is the cleaning plan's (Clean with AI).
import { AlertTriangle, CircleDashed, Flag } from "lucide-react";
import type { ReactNode } from "react";
import { useDatacard } from "@/api/queries";
import type { DataCard, Dataset, Issue } from "@/api/types";
import { issueLine } from "./CleanPlanPanel";

export function summaryLines(card: DataCard): Issue[] {
  return [...card.issues].sort((a, b) => b.severity - a.severity).slice(0, 3);
}

export function CleaningOffer({ dataset, actions }: { dataset: Dataset; actions?: ReactNode }) {
  const { data: card } = useDatacard(dataset.id);
  const top = card ? summaryLines(card) : [];
  return (
    <div className="mx-auto mt-[8vh] w-full max-w-[640px] px-4">
      <div className="rounded-2xl border border-border bg-card p-7">
        <h2 className="font-serif text-[32px] leading-tight">Here's what I found in {dataset.name}</h2>
        {card && (
          <p className="mt-2 text-muted-foreground">
            {card.row_count.toLocaleString()} rows · {card.column_count} columns ·{" "}
            {card.issues.length === 1 ? "1 issue" : `${card.issues.length} issues`}
          </p>
        )}
        <ul className="mt-5 flex flex-col gap-2">
          {top.map((i) => (
            <li key={i.id} className="flex items-center gap-2.5">
              {i.detector === "leakage" ? (
                <Flag className="size-4 text-warning" aria-hidden />
              ) : i.detector === "missing" ? (
                <CircleDashed className="size-4 text-muted-foreground" aria-hidden />
              ) : (
                <AlertTriangle className="size-4 text-muted-foreground" aria-hidden />
              )}
              {issueLine(i)}
            </li>
          ))}
          {card && !card.issues.length && <li className="text-muted-foreground">Nothing that needs cleaning.</li>}
        </ul>
        {actions}
      </div>
    </div>
  );
}
