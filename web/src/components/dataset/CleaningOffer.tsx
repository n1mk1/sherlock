// The cleaning offer (App Flow §4): what profiling found, number first: the count, the three most severe
// issues, for the cleaning depth the slider picks (PRD CLEAN-15). The full list is the cleaning plan's
// (Clean with AI), which opens at that depth.
import { AlertTriangle, CircleDashed, Flag } from "lucide-react";
import { useId, useState, type CSSProperties, type ReactNode } from "react";
import { useDatacard, useDetectorDepth, useDetectorLabel, useDetectors, useMe } from "@/api/queries";
import type { DataCard, Dataset, Depth, Issue } from "@/api/types";
import { Pill } from "@/components/ui/pill";
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
    <div className="flex h-full overflow-y-auto">
      <div className="m-auto flex w-full max-w-[560px] flex-col px-6 py-8">
        {card && (
          <>
            <p className="type-label tnum">
              {card.row_count.toLocaleString()} rows · {card.column_count} columns
            </p>
            <h2 className="mt-2 type-display">
              {shown ? `${shown.toLocaleString()} ${shown === 1 ? "issue" : "issues"} to look at` : deeper ? "Nothing at this depth" : "Nothing to clean"}
            </h2>
            {deeper > 0 && <p className="mt-1.5 text-[14px] text-muted-foreground">{deeper} more in deeper layers</p>}
          </>
        )}
        {top.length > 0 && (
          <ul className="mt-6 flex flex-col">
            {top.map((i) => (
              <li key={i.id} className="flex items-center gap-3 border-b border-border py-3 text-[14px] last:border-b-0">
                <span className={cn("inline-flex size-7 shrink-0 items-center justify-center rounded-full [&_svg]:size-3.5",
                  i.detector === "leakage" ? "bg-amber-soft text-amber" : i.detector === "missing" ? "bg-secondary text-muted-foreground" : "bg-amber-soft text-amber")}
                  aria-hidden>
                  {i.detector === "leakage" ? <Flag /> : i.detector === "missing" ? <CircleDashed /> : <AlertTriangle />}
                </span>
                <span className="tnum">{issueLine(i, label)}</span>
              </li>
            ))}
          </ul>
        )}
        {card && !shown && deeper > 0 && <p className="mt-4 text-[14px] text-muted-foreground">Drag right to look deeper.</p>}
        <DepthSlider depth={depth} onChange={setPicked} />
        {actions?.(depth)}
      </div>
    </div>
  );
}

// Cleaning depth (PRD CLEAN-15): layer 1 looks only at single values; each step right adds a layer that
// looks at a wider part of the data. The line under it names the checks the layer adds.
export function DepthSlider({ depth, onChange }: { depth: Depth; onChange: (d: Depth) => void }) {
  const id = useId();
  const { data } = useDetectors();
  const layer = LAYERS[depth - 1];
  // The user's own checks (`rule`) run at every depth, so they aren't one layer's.
  const adds = (data?.detectors ?? []).filter((d) => d.depth === depth && d.id !== "rule").map((d) => d.label);
  return (
    <div className="mt-8 rounded-2xl bg-background p-5">
      <div className="flex items-center justify-between gap-3">
        <label htmlFor={id} className="text-[14px] font-medium">Cleaning depth</label>
        <Pill tone="violet" size="sm">{layer.name}</Pill>
      </div>
      <input id={id} type="range" min={1} max={LAYERS.length} step={1} value={depth}
        aria-valuetext={`Layer ${depth} of ${LAYERS.length}: ${layer.name}`}
        onChange={(e) => onChange(Number(e.target.value) as Depth)}
        className="range mt-4 w-full" style={{ "--fill": `${((depth - 1) / (LAYERS.length - 1)) * 100}%` } as CSSProperties} />
      <div className="mt-2 grid grid-cols-5 text-[11.5px] text-muted-foreground" aria-hidden>
        {LAYERS.map((l, n) => (
          <span key={l.name} className={cn(n === 0 ? "text-left" : n === LAYERS.length - 1 ? "text-right" : "text-center",
            n < depth && "text-foreground")}>{l.name}</span>
        ))}
      </div>
      <p className="mt-3 text-[13px] leading-snug text-muted-foreground">
        Looks at {layer.looks}{adds.length ? `: ${adds.join(", ")}` : ""}.
      </p>
    </div>
  );
}
