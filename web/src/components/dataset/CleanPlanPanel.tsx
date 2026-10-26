// The cleaning plan (App Flow §4, UI brief §5.3a, PRD CLEAN-8a): what Clean with AI will try on the current
// version, diagnosed by Sherlock's code detectors, grouped into modules, every fix ticked. The user unticks
// what they don't want, then starts. Leakage and ID columns are info rows under "Marked, not changed".
// From the offer it fills the centre (`layout="centre"`); from the CSV tab it replaces Changes in the right
// panel (`layout="side"`), with the scope radios, so the grid stays visible.
import { useIsMutating } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Flag, Loader2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { makeSelection } from "@/api/csv";
import {
  stalePlan, useCleanPlan, useDiscardPlan, usePlanOps, useStartCleaning, type CleanScope,
} from "@/api/queries";
import type { CleanPlan, CleanPlanItem, Dataset, Issue, PlanModule } from "@/api/types";
import { useSettingsOpen } from "@/components/shell/SettingsDialog";
import { Button } from "@/components/ui/button";
import { displayValue } from "@/lib/cells";
import { cn } from "@/lib/utils";
import { pendingCount, useEdits } from "@/state/edits";
import { useUi } from "@/state/ui";

export const LABELS: Record<string, string> = {
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

export function issueLine(i: Pick<Issue, "detector" | "column" | "count">): string {
  const what = LABELS[i.detector] ?? i.detector.replace(/_/g, " ");
  if (i.detector === "leakage" || i.detector === "id_candidates") return `${i.column} ${what}`;
  return `${i.count.toLocaleString()} ${what}${i.column ? ` in ${i.column}` : ""}`;
}

// Display order (`cleaning/plan.py` MODULES).
const MODULES: [PlanModule, string][] = [
  ["yours", "Your steps"],
  ["types", "Types and parsing"],
  ["missing", "Missing and placeholder values"],
  ["text", "Spelling and formatting"],
  ["records", "Duplicates and broken records"],
  ["outliers", "Outliers"],
  ["other", "Other checks"],
  ["kept", "Marked, not changed"],
];
const ISSUE_BUDGET = 20; // CLEAN_MAX_STEPS's default: issues attempted per run (PRD CLEAN-9)
const AFTER_UPLOAD_LABEL = "Open the cleaning plan";

export function CleanPlanPanel({ dataset, layout }: { dataset: Dataset; layout: "centre" | "side" }) {
  const creating = useIsMutating({ mutationKey: ["create-plan", dataset.id] }) > 0;
  const { data: plan } = useCleanPlan(dataset.clean_plan_id);
  const shell = layout === "centre"
    ? "mx-auto mt-[6vh] w-full max-w-[720px] px-4 pb-8"
    : "flex h-full flex-col overflow-y-auto";
  if (!plan || plan.status !== "draft") {
    return (
      <div className={shell}>
        <div className={cn("flex items-center gap-3", layout === "centre" ? "rounded-2xl border border-border bg-card p-7" : "p-4")} role="status">
          <Loader2 className="size-5 animate-spin text-muted-foreground" aria-hidden />
          <p className="text-[15px]">{creating || dataset.clean_plan_id ? `Diagnosing v${dataset.current_version} of ${dataset.name}…` : "No cleaning plan open."}</p>
        </div>
      </div>
    );
  }
  return (
    <div className={shell}>
      <PlanBody dataset={dataset} plan={plan} layout={layout} />
    </div>
  );
}

function PlanBody({ dataset, plan, layout }: { dataset: Dataset; plan: CleanPlan; layout: "centre" | "side" }) {
  const ops = usePlanOps(plan);
  const start = useStartCleaning(dataset.id);
  const discard = useDiscardPlan(dataset.id);
  const [, , openSettingsAt] = useSettingsOpen();
  const side = layout === "side";
  const [scope, setScope] = useState<CleanScope["kind"]>("all");
  const csvSelection = useUi((s) => s.csvSelection);
  const selected = csvSelection?.row_ids.length ?? 0;
  useEffect(() => {
    if (scope === "selection" && selected === 0) setScope("all");
  }, [scope, selected]);
  const pending = pendingCount(useEdits((s) => s.buffers[dataset.id]));
  const discardEdits = useEdits((s) => s.discard);
  const unsaved = side && pending > 0;

  // The plan's notes say what a merge onto a newer version changed.
  const shownNotes = useRef<string>("");
  useEffect(() => {
    const text = (plan.notes ?? []).join(" ");
    if (text && text !== shownNotes.current) {
      shownNotes.current = text;
      toast(text);
    }
  }, [plan.notes]);

  const groups = useMemo(
    () => MODULES.map(([m, title]) => ({ module: m, title, items: plan.items.filter((i) => i.module === m) })).filter((g) => g.items.length),
    [plan.items],
  );
  const changeable = plan.items.filter((i) => i.change);
  const ticked = changeable.filter((i) => i.ticked).length;
  const send = (body: Parameters<typeof ops.mutate>[0]) =>
    ops.mutate(body, { onError: (e) => toast.error((e as Error).message) });

  const begin = async () => {
    try {
      let s: CleanScope = { kind: "all" };
      if (side && scope === "selection" && csvSelection) {
        const sel = await makeSelection(dataset.id, csvSelection.row_ids, "Clean with AI");
        s = { kind: "selection", selection_id: sel.selection_id };
      } else if (side && scope === "new_rows") {
        s = { kind: "new_rows" };
      }
      await start.mutateAsync({ plan_id: plan.id, scope: s });
      if (side) toast("Cleaning started. Its steps appear in Changes as they commit.");
    } catch (e) {
      if (stalePlan(e)) toast("The data changed; the plan was updated.");
      else toast.error((e as Error).message);
    }
  };

  return (
    <section aria-labelledby="plan-title" className={cn(side ? "flex flex-col gap-3 p-4" : "rounded-2xl border border-border bg-card p-7")}>
      <header>
        <h2 id="plan-title" className={side ? "text-[15px] font-semibold" : "font-serif text-[32px] leading-tight"}>
          Cleaning plan · v{plan.version}
        </h2>
        <p className={cn("text-muted-foreground", side ? "mt-1 text-[13px]" : "mt-2")}>
          Sherlock checked v{plan.version}. Untick what you don't want cleaned, then start.
        </p>
        {plan.source === "after_upload" && !side && (
          <p className="mt-2 text-[13px] text-muted-foreground">
            Opened because After upload is “{AFTER_UPLOAD_LABEL}” ·{" "}
            <Button variant="link" size="sm" className="text-[13px]" onClick={() => openSettingsAt("after_upload")}>Change</Button>
          </p>
        )}
      </header>

      {side && (
        <fieldset className="flex flex-col gap-1.5 text-[13px]">
          <legend className="mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Scope</legend>
          {([
            ["all", "Whole dataset"],
            ["selection", `Current selection (${selected.toLocaleString()} rows)`],
            ["new_rows", "Rows added since the last clean"],
          ] as const).map(([v, label]) => (
            <label key={v} className={cn("flex items-center gap-2", v === "selection" && selected === 0 && "opacity-40")}>
              <input type="radio" name="plan-scope" checked={scope === v} disabled={v === "selection" && selected === 0}
                onChange={() => setScope(v)} className="accent-[var(--accent)]" />
              {label}
            </label>
          ))}
          {scope !== "all" && (
            <p className="text-[12px] text-muted-foreground">Counts are for the whole file; changes stay inside the rows in scope.</p>
          )}
        </fieldset>
      )}

      <div className={cn("flex flex-col", side ? "gap-3" : "mt-6 gap-5")}>
        {groups.map((g) => (
          <ModuleGroup key={g.module} module={g.module} title={g.title} items={g.items} side={side} busy={ops.isPending}
            onTick={(item, on) => send([{ op: on ? "tick" : "untick", item_id: item.id }])}
            onTickModule={(on) => send([{ op: on ? "tick_module" : "untick_module", module: g.module }])} />
        ))}
        {!changeable.length && <p className="text-muted-foreground">Nothing that needs cleaning.</p>}
      </div>

      <div className={cn("flex flex-col gap-1.5", side ? "border-t border-border pt-3" : "mt-6")}>
        <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Mode</span>
        <div role="radiogroup" aria-label="Mode" className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px]">
          <label className="flex items-center gap-2">
            <input type="radio" name={`plan-mode-${layout}`} checked readOnly className="accent-[var(--accent)]" /> Run on its own
          </label>
          <label className="flex items-center gap-2 text-muted-foreground opacity-60" title="Step-by-step cleaning comes in a later release">
            <input type="radio" name={`plan-mode-${layout}`} disabled /> Ask me before each fix <span className="text-[12px]">comes later</span>
          </label>
        </div>
      </div>

      <footer className={cn("flex flex-col gap-2", side ? "sticky bottom-0 -mx-4 border-t border-border bg-background px-4 py-3" : "mt-6 border-t border-border pt-4")}>
        <p className="text-[13px] text-muted-foreground">
          {ticked} of {changeable.length} ticked
          {ticked > ISSUE_BUDGET && ` · Sherlock tries up to ${ISSUE_BUDGET} per run, the most severe first`}
        </p>
        {unsaved && (
          <div className="rounded-md bg-muted p-2.5 text-[12px]">
            Save or discard your {pending} unsaved {pending === 1 ? "change" : "changes"} first.
            <Button size="sm" variant="ghost" className="ml-2" onClick={() => discardEdits(dataset.id)}>Discard edits</Button>
          </div>
        )}
        <p className="text-[12px] text-muted-foreground">Cells you edited by hand are left alone and listed in the report.</p>
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" size={side ? "sm" : "default"} loading={discard.isPending}
            onClick={() => discard.mutate(plan.id, { onError: (e) => toast.error((e as Error).message) })}>Discard</Button>
          <Button variant="primary" size={side ? "sm" : "default"} loading={start.isPending}
            disabled={ticked === 0 || unsaved || ops.isPending} onClick={begin}
            title={ticked === 0 ? "Tick at least one fix" : unsaved ? "Save or discard your edits first" : undefined}>
            Start cleaning ({ticked})
          </Button>
        </div>
      </footer>
    </section>
  );
}

function ModuleGroup({ module, title, items, side, busy, onTick, onTickModule }: {
  module: PlanModule; title: string; items: CleanPlanItem[]; side: boolean; busy: boolean;
  onTick: (item: CleanPlanItem, on: boolean) => void; onTickModule: (on: boolean) => void;
}) {
  const kept = module === "kept";
  const on = items.filter((i) => i.ticked).length;
  const box = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (box.current) box.current.indeterminate = on > 0 && on < items.length;
  }, [on, items.length]);
  const headingId = `plan-module-${module}`;
  return (
    <section aria-labelledby={headingId}>
      <div className="flex items-center gap-2 border-b border-border pb-1.5">
        {!kept && (
          <input ref={box} type="checkbox" checked={on === items.length} disabled={busy}
            aria-label={`${title}: tick all`} onChange={(e) => onTickModule(e.target.checked)} className="accent-[var(--accent)]" />
        )}
        <h3 id={headingId} className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{title}</h3>
        {!kept && <span className="ml-auto shrink-0 whitespace-nowrap font-mono text-[12px] text-muted-foreground">{on} of {items.length}</span>}
      </div>
      <ul className="flex flex-col">
        {items.map((i) => <ItemRow key={i.id} item={i} side={side} busy={busy} onTick={(v) => onTick(i, v)} />)}
      </ul>
    </section>
  );
}

function ItemRow({ item, side, busy, onTick }: { item: CleanPlanItem; side: boolean; busy: boolean; onTick: (on: boolean) => void }) {
  const [open, setOpen] = useState(false);
  const label = LABELS[item.detector] ?? item.detector.replace(/_/g, " ");
  const name = `${item.column ?? "rows"}: ${label}`;
  return (
    <li className="border-b border-border py-2 last:border-b-0">
      <div className="flex items-start gap-2">
        {item.change ? (
          <input type="checkbox" checked={item.ticked} disabled={busy} aria-label={name} onChange={(e) => onTick(e.target.checked)}
            className="mt-0.5 shrink-0 accent-[var(--accent)]" />
        ) : (
          <Flag className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
        )}
        <div className={cn("min-w-0 flex-1", !side && "flex flex-wrap items-baseline gap-x-3")}>
          <span className="font-mono text-[13px]">{item.column ?? "rows"}</span>{" "}
          <span className={cn(!item.ticked && item.change && "text-muted-foreground")}>{label}</span>
          {item.count !== null && <span className="ml-1.5 font-mono text-[12.5px] text-muted-foreground">{item.count.toLocaleString()}</span>}
          <p className={cn("text-[12.5px] text-muted-foreground", !side && "basis-full")}>{item.change ? item.action : item.reason}</p>
        </div>
        {item.examples.length > 0 && (
          <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
            aria-label={open ? `Hide examples of ${name}` : `Show examples of ${name}`}
            className="mt-0.5 shrink-0 rounded p-0.5 text-muted-foreground hover:bg-secondary hover:text-foreground">
            {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
          </button>
        )}
      </div>
      {open && (
        <ul className="mt-1.5 flex flex-wrap gap-1.5 pl-6" aria-label={`Examples of ${name}`}>
          {item.examples.map((v, n) => (
            <li key={n} className="max-w-[240px] truncate rounded-md border border-border bg-muted px-1.5 py-0.5 font-mono text-[12px]">
              {displayValue(v) || "—"}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}
