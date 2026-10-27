// The cleaning offer (App Flow §4, UI brief §5.3): what profiling found, in plain words: the counts and
// the three most severe issues, for the cleaning depth the slider picks (PRD CLEAN-15). The full list is
// the cleaning plan's (Clean with AI), which opens at that depth.
import { AlertTriangle, CircleDashed, Flag } from "lucide-react";
import { useId, useState, type ReactNode } from "react";
import { useDatacard, useDetectorDepth, useDetectorLabel, useDetectors, useMe } from "@/api/queries";
import type { DataCard, Dataset, Depth, Issue } from "@/api/types";
import { cn } from "@/lib/utils";
import { issueLine } from "./CleanPlanPanel";
import { LAYERS } from "./depth";

// The three issues to lead with: a column that's never changed first (it records the outcome or is an ID,
// as the queue puts it), then by code's default level (PRD CLEAN-8c), breaks first, then by size. A card
// from before levels sorts by size alone.
const RANK: Record<string, number> = { breaks: 0, skews: 1, splits: 2, check: 3, cosmetic: 4 };

export function summaryLines(card: DataCard, keep: (i: Issue) => boolean = () => true): Issue[] {
  const levelled = card.issues.some((x) => x.level);
  const rank = (i: Issue) => (!levelled ? 0 : i.level ? RANK[i.level] ?? 5 : -1);
  return card.issues.filter(keep).sort((a, b) => rank(a) - rank(b) || b.severity - a.severity).slice(0, 3);
}

export function CleaningOffer({ dataset, actions }: { dataset: Dataset; actions?: (depth: Depth) => ReactNode }) {
  const { data: card } = useDatacard(dataset.id);
  const { data: me } = useMe();
  const label = useDetectorLabel();
  const depthOf = useDetectorDepth();
  const [picked, setPicked] = useState<Depth | null>(null);
  const depth = picked ?? me?.settings.clean_depth ?? 5;
  const within = (i: Issue) => depthOf(i) <= depth;
  const shown = card ? card.issues.filter(within).length : 0;
  const deeper = card ? card.issues.length - shown : 0;
  const top = card ? summaryLines(card, within) : [];
  return (
    <div className="mx-auto mt-[8vh] w-full max-w-[640px] px-4">
      <div className="rounded-2xl border border-border bg-card p-7">
        <h2 className="font-serif text-[32px] leading-tight">Here's what I found in {dataset.name}</h2>
        {card && (
          <p className="mt-2 text-muted-foreground">
            {card.row_count.toLocaleString()} rows · {card.column_count} columns ·{" "}
            {shown === 1 ? "1 issue" : `${shown} issues`}
            {deeper > 0 && ` · ${deeper} more in deeper layers`}
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
          {card && !shown && (
            <li className="text-muted-foreground">
              {deeper ? "Nothing at this depth. Drag right to look deeper." : "Nothing that needs cleaning."}
            </li>
          )}
        </ul>
        <DepthSlider depth={depth} onChange={setPicked} />
        {actions?.(depth)}
      </div>
    </div>
  );
}

// Cleaning depth (PRD CLEAN-15, UI brief §5.3): layer 1 looks only at single values; each step right adds
// a layer that looks at a wider part of the data. The line under it names the checks the layer adds.
export function DepthSlider({ depth, onChange }: { depth: Depth; onChange: (d: Depth) => void }) {
  const id = useId();
  const { data } = useDetectors();
  const layer = LAYERS[depth - 1];
  // The user's own checks (`rule`) run at every depth, so they aren't one layer's.
  const adds = (data?.detectors ?? []).filter((d) => d.depth === depth && d.id !== "rule").map((d) => d.label);
  return (
    <div className="mt-6">
      <div className="flex items-baseline justify-between gap-3">
        <label htmlFor={id} className="text-[14px] font-medium">Cleaning depth</label>
        <span className="text-[13px] text-muted-foreground">Layer {depth} of {LAYERS.length} · {layer.name}</span>
      </div>
      <input id={id} type="range" min={1} max={LAYERS.length} step={1} value={depth}
        aria-valuetext={`Layer ${depth} of ${LAYERS.length}: ${layer.name}`}
        onChange={(e) => onChange(Number(e.target.value) as Depth)}
        className="mt-2 w-full cursor-pointer accent-[var(--accent)]" />
      <div className="mt-1 grid grid-cols-5 text-[12px] text-muted-foreground" aria-hidden>
        {LAYERS.map((l, n) => (
          <span key={l.name} className={cn(n === 0 ? "text-left" : n === LAYERS.length - 1 ? "text-right" : "text-center",
            n < depth && "text-foreground")}>{l.name}</span>
        ))}
      </div>
      <p className="mt-2 text-[13px] text-muted-foreground">
        Looks at {layer.looks}{adds.length ? `: ${adds.join(", ")}` : ""}.
      </p>
    </div>
  );
}
