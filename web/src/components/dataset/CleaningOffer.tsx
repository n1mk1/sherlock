// The cleaning offer (App Flow §4, UI brief §5.3): what profiling found, in plain words.
import { AlertTriangle, CircleDashed, Flag } from "lucide-react";
import type { ReactNode } from "react";
import { useDatacard } from "@/api/queries";
import type { DataCard, Dataset, Issue } from "@/api/types";

const LABELS: Record<string, string> = {
  missing: "missing",
  mixed_types: "mixed types",
  sentinels: "placeholder values",
  whitespace_case: "spacing or case variants",
  near_duplicate_categories: "near-duplicate categories",
  duplicates: "duplicate rows",
  impossible_values: "impossible values",
  numbers_as_text: "numbers stored as text",
  ambiguous_dates: "ambiguous dates",
  mojibake: "garbled characters",
  unit_mixes: "mixed units",
  cross_column: "values out of order",
  functional_dependency: "broken dependencies",
  id_candidates: "looks like an ID",
  outliers: "outliers",
  leakage: "records the outcome",
};

export function issueLine(i: Issue): string {
  const what = LABELS[i.detector] ?? i.detector.replace(/_/g, " ");
  if (i.detector === "leakage" || i.detector === "id_candidates") return `${i.column} ${what}`;
  return `${i.count.toLocaleString()} ${what}${i.column ? ` in ${i.column}` : ""}`;
}

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
        {card && card.issues.length > 3 && (
          <details className="mt-4 text-[13px]">
            <summary className="cursor-pointer text-accent">All {card.issues.length} issues</summary>
            <table className="mt-2 w-full">
              <tbody>
                {card.issues.map((i) => (
                  <tr key={i.id} className="border-b border-border">
                    <td className="py-1.5 pr-3 font-mono">{i.column ?? "rows"}</td>
                    <td className="py-1.5 pr-3">{LABELS[i.detector] ?? i.detector}</td>
                    <td className="py-1.5 pr-3 text-right font-mono">{i.count.toLocaleString()}</td>
                    <td className="py-1.5 text-muted-foreground">{i.proposal}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        )}
        {actions}
      </div>
    </div>
  );
}
