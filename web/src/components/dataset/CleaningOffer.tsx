// The cleaning offer (App Flow §4, UI brief §5.3): what profiling found, in plain words: the counts and
// the three most severe issues. The full list is the cleaning plan's (Clean with AI).
import { AlertTriangle, CircleDashed, Flag } from "lucide-react";
import type { ReactNode } from "react";
import { useDatacard, useDetectorLabel } from "@/api/queries";
import type { DataCard, Dataset, Issue } from "@/api/types";
import { issueLine } from "./CleanPlanPanel";

// The three issues to lead with: a column that's never changed first (it records the outcome or is an ID,
// as the queue puts it), then by code's default level (PRD CLEAN-8c), breaks first, then by size. A card
// from before levels sorts by size alone.
const RANK: Record<string, number> = { breaks: 0, skews: 1, splits: 2, check: 3, cosmetic: 4 };

export function summaryLines(card: DataCard): Issue[] {
  const levelled = card.issues.some((x) => x.level);
  const rank = (i: Issue) => (!levelled ? 0 : i.level ? RANK[i.level] ?? 5 : -1);
  return [...card.issues].sort((a, b) => rank(a) - rank(b) || b.severity - a.severity).slice(0, 3);
}

export function CleaningOffer({ dataset, actions }: { dataset: Dataset; actions?: ReactNode }) {
  const { data: card } = useDatacard(dataset.id);
  const label = useDetectorLabel();
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
              {issueLine(i, label)}
            </li>
          ))}
          {card && !card.issues.length && <li className="text-muted-foreground">Nothing that needs cleaning.</li>}
        </ul>
        {actions}
      </div>
    </div>
  );
}
