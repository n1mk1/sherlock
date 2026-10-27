// The cleaning plan (App Flow §4, UI brief §5.3a, PRD CLEAN-8a): what Clean with AI will try on the current
// version, diagnosed by Sherlock's code detectors, grouped into modules, every fix ticked. The user unticks
// what they don't want, rewrites a fix in plain words (✎), adds steps of their own (PRD CLEAN-8b) or asks
// the chat to do any of that, then starts. Leakage and ID columns are info rows under "Marked, not changed".
// While it's open, the chat bar sends its `plan_id`, so chat can change it.
// From the offer it fills the centre (`layout="centre"`); from the CSV tab it replaces Changes in the right
// panel (`layout="side"`), with the scope radios, so the grid stays visible. A plan opened for some rows
// (the new-rows toast's "Clean them", chat's "clean these rows") starts on those rows (PRD CLEAN-1).
// An ambiguous-dates fix asks which order its dates are written in, with three values read both ways
//; dates that every one reads both ways are cleaned only once the order is picked.
import { useIsMutating } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Flag, Loader2, Pencil, Plus, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { makeSelection } from "@/api/csv";
import {
  stalePlan, useCleanPlan, useDatacard, useDetectorLabel, useDetectors, useDiscardPlan, usePlanOps, useStartCleaning, type CleanScope,
} from "@/api/queries";
import type { CleanPlan, CleanPlanItem, Dataset, Issue, PlanModule, PlanOp, PlanScope } from "@/api/types";
import { useSettingsOpen } from "@/components/shell/SettingsDialog";
import { Button } from "@/components/ui/button";
import { displayValue } from "@/lib/cells";
import { cn } from "@/lib/utils";
import { pendingCount, useEdits } from "@/state/edits";
import { useUi } from "@/state/ui";

// "263 missing values in age", or "name looks like an ID"; `label` is `useDetectorLabel()`.
export function issueLine(i: Pick<Issue, "detector" | "column" | "count">, label: (detector: string) => string): string {
  const what = label(i.detector);
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
const MAX_INSTRUCTION = 500; // cleaning/plan.py MAX_INSTRUCTION
const AFTER_UPLOAD_LABEL = "Open the cleaning plan";

/** The scope radio for rows the plan was opened for. */
export function presetLabel(s: PlanScope): string {
  const n = s.rows ?? 0;
  const rows = `${n.toLocaleString()} ${n === 1 ? "row" : "rows"}`;
  if (s.kind === "new_rows") return s.rows ? `The ${rows} you just added` : "Rows added since the last clean";
  return `The ${rows} you asked to clean`;
}

export function CleanPlanPanel({ dataset, layout }: { dataset: Dataset; layout: "centre" | "side" }) {
  const creating = useIsMutating({ mutationKey: ["create-plan", dataset.id] }) > 0;
  const { data: plan } = useCleanPlan(dataset.clean_plan_id);
  useDetectors(); // fetched while the plan loads, so its items show their labels at once
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
  const preset = plan.scope;
  const [scope, setScope] = useState<CleanScope["kind"] | "preset">(preset ? "preset" : "all");
  const presetKey = preset ? JSON.stringify(preset) : "";
  useEffect(() => {
    if (presetKey) setScope("preset"); // "Clean them" or chat set the plan's rows: show them picked
  }, [presetKey]);
  const csvSelection = useUi((s) => s.csvSelection);
  const selected = csvSelection?.row_ids.length ?? 0;
  useEffect(() => {
    if ((scope === "selection" && selected === 0) || (scope === "preset" && !preset)) setScope("all");
  }, [scope, selected, preset]);
  const pending = pendingCount(useEdits((s) => s.buffers[dataset.id]));
  const discardEdits = useEdits((s) => s.discard);
  const unsaved = side && pending > 0;
  // Open ✎ editors (and the Add a step form) with text that isn't saved yet: Start waits for them.
  const [dirty, setDirty] = useState<Record<string, boolean>>({});
  const markDirty = (id: string, on: boolean) => setDirty((d) => (d[id] === on ? d : { ...d, [id]: on }));
  const editing = Object.values(dirty).some(Boolean);
  // The chat bar sends this plan's id while it's open, so the chat can change it (TRD §8.2 edit_plan).
  const setPlanId = useUi((s) => s.setPlanId);
  useEffect(() => {
    setPlanId(plan.id);
    return () => { if (useUi.getState().planId === plan.id) setPlanId(null); };
  }, [plan.id, setPlanId]);

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
  const send = (body: PlanOp[], onDone?: () => void) =>
    ops.mutate(body, { onError: (e) => toast.error((e as Error).message), onSuccess: () => onDone?.() });

  const begin = async () => {
    try {
      let s: CleanScope = { kind: "all" };
      if (scope === "preset" && preset) {
        s = preset.kind === "selection"
          ? { kind: "selection", selection_id: preset.selection_id ?? undefined }
          : { kind: "new_rows", row_ids: preset.row_ids ?? undefined };
      } else if (side && scope === "selection" && csvSelection) {
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
          {plan.version < dataset.current_version
            // A new version arrived while the plan was open; reading it again merges it onto that version.
            ? `Sherlock checked v${plan.version}; the data is v${dataset.current_version}. Checking the plan again…`
            : `Sherlock checked v${plan.version}. Untick, edit or add steps, or ask in chat.`}
        </p>
        {plan.source === "after_upload" && !side && (
          <p className="mt-2 text-[13px] text-muted-foreground">
            Opened because After upload is “{AFTER_UPLOAD_LABEL}” ·{" "}
            <Button variant="link" size="sm" className="text-[13px]" onClick={() => openSettingsAt("after_upload")}>Change</Button>
          </p>
        )}
        {preset && !side && (
          <p className="mt-2 text-[13px] text-muted-foreground">Only {presetLabel(preset).charAt(0).toLowerCase() + presetLabel(preset).slice(1)}.</p>
        )}
      </header>

      {side && (
        <fieldset className="flex flex-col gap-1.5 text-[13px]">
          <legend className="mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Scope</legend>
          {([
            ...(preset ? [["preset", presetLabel(preset)] as const] : []),
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
            send={send} onDirty={markDirty}
            onTickModule={(on) => send([{ op: on ? "tick_module" : "untick_module", module: g.module }])} />
        ))}
        {!changeable.length && <p className="text-muted-foreground">Nothing that needs cleaning yet. Add a step of your own below.</p>}
        <AddStep datasetId={dataset.id} busy={ops.isPending} send={send} onDirty={(on) => markDirty("add", on)} />
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
          {ticked > ISSUE_BUDGET && ` · Sherlock tries up to ${ISSUE_BUDGET} per run; your steps first, then the most severe`}
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
            disabled={ticked === 0 || unsaved || editing || ops.isPending} onClick={begin}
            title={ticked === 0 ? "Tick at least one fix" : unsaved ? "Save or discard your edits first"
              : editing ? "Save or cancel the step you're editing first" : undefined}>
            Start cleaning ({ticked})
          </Button>
        </div>
      </footer>
    </section>
  );
}

type Send = (ops: PlanOp[], onDone?: () => void) => void;

const ORDERS = [["dmy", "Day first"], ["mdy", "Month first"]] as const;

/** "Which order are these dates in?": three values read both ways, and Day first · Month first. */
export function DateOrder({ item, busy, onPick }: {
  item: CleanPlanItem; busy: boolean; onPick: (order: "dmy" | "mdy" | null) => void;
}) {
  const ways = (item.both_ways ?? []).slice(0, 3);
  const chosen = item.date_order ?? null;
  const groupId = `date-order-${item.id}`;
  return (
    <div className="mt-1.5 flex flex-col gap-1.5 pl-6 text-[12.5px]">
      <p id={groupId} className="font-medium">Which order are these dates in?</p>
      <table className="w-fit font-mono text-[12px]">
        <thead className="text-muted-foreground">
          <tr><th className="pr-3 text-left font-normal">Value</th><th className="pr-3 text-left font-normal">Day first</th>
            <th className="text-left font-normal">Month first</th></tr>
        </thead>
        <tbody>
          {ways.map((w) => (
            <tr key={w.value}>
              <td className="pr-3">{w.value}</td>
              <td className={cn("pr-3", chosen === "dmy" && "text-accent")}>{w.day_first}</td>
              <td className={cn(chosen === "mdy" && "text-accent")}>{w.month_first}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div role="radiogroup" aria-labelledby={groupId} className="flex gap-1.5">
        {ORDERS.map(([order, label]) => (
          <button key={order} type="button" role="radio" aria-checked={chosen === order} disabled={busy}
            onClick={() => onPick(chosen === order ? null : order)}
            className={cn("h-7 rounded-md border px-2.5 text-[12.5px]",
              chosen === order ? "border-primary bg-primary text-primary-foreground" : "border-border-strong hover:bg-secondary")}>
            {label}
          </button>
        ))}
      </div>
      {!chosen && (
        <p className="text-muted-foreground">
          {item.needs_order ? "Every date here reads both ways, so Sherlock won't guess: without an order they stay text."
            : "Sherlock reads the dates that show their order; pick one to decide the rest."}
        </p>
      )}
    </div>
  );
}

function ModuleGroup({ module, title, items, side, busy, send, onDirty, onTickModule }: {
  module: PlanModule; title: string; items: CleanPlanItem[]; side: boolean; busy: boolean;
  send: Send; onDirty: (id: string, on: boolean) => void; onTickModule: (on: boolean) => void;
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
        {items.map((i) => <ItemRow key={i.id} item={i} side={side} busy={busy} send={send} onDirty={(on) => onDirty(i.id, on)} />)}
      </ul>
    </section>
  );
}

function ItemRow({ item, side, busy, send, onDirty }: {
  item: CleanPlanItem; side: boolean; busy: boolean; send: Send; onDirty: (on: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const label = useDetectorLabel()(item.detector);
  const name = `${item.column ?? "rows"}: ${label}`;
  const yours = item.key === null;
  const onTick = (on: boolean) => send([{ op: on ? "tick" : "untick", item_id: item.id }]);
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
          {!item.change ? (
            <p className={cn("text-[12.5px] text-muted-foreground", !side && "basis-full")}>{item.reason}</p>
          ) : item.instruction && !yours ? (
            <div className={cn("text-[12.5px]", !side && "basis-full")}>
              <p>{item.instruction} <span className="rounded bg-accent-soft px-1 text-[11px] text-accent">edited</span></p>
              <p className="text-muted-foreground line-through decoration-muted-foreground/40">{item.action}</p>
            </div>
          ) : (
            <p className={cn("text-[12.5px]", yours ? "text-foreground" : "text-muted-foreground", !side && "basis-full")}>
              {item.action}{item.source === "chat" && <span className="ml-1.5 text-[11px] text-muted-foreground">· from chat</span>}
            </p>
          )}
        </div>
        {item.change && !editing && (
          <button type="button" onClick={() => setEditing(true)} disabled={busy}
            aria-label={yours ? `Edit your step on ${item.column ?? "the rows"}` : `Rewrite the fix for ${name}`}
            className="mt-0.5 shrink-0 rounded p-0.5 text-muted-foreground hover:bg-secondary hover:text-foreground">
            <Pencil className="size-3.5" />
          </button>
        )}
        {yours && (
          <button type="button" onClick={() => send([{ op: "remove", item_id: item.id }])} disabled={busy}
            aria-label={`Remove your step on ${item.column ?? "the rows"}`}
            className="mt-0.5 shrink-0 rounded p-0.5 text-muted-foreground hover:bg-secondary hover:text-foreground">
            <X className="size-3.5" />
          </button>
        )}
        {item.examples.length > 0 && (
          <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open}
            aria-label={open ? `Hide examples of ${name}` : `Show examples of ${name}`}
            className="mt-0.5 shrink-0 rounded p-0.5 text-muted-foreground hover:bg-secondary hover:text-foreground">
            {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
          </button>
        )}
      </div>
      {item.change && item.both_ways && item.both_ways.length > 0 && (
        <DateOrder item={item} busy={busy} onPick={(order) => send([{ op: "set_date_order", item_id: item.id, order }])} />
      )}
      {editing && (
        <InstructionEditor item={item} busy={busy} onDirty={onDirty}
          onCancel={() => { onDirty(false); setEditing(false); }}
          onSave={(instruction) => send([{ op: "set_instruction", item_id: item.id, instruction }],
                                       () => { onDirty(false); setEditing(false); })} />
      )}
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

/** ✎: the fix (or the user's step) in plain words. Reset puts Sherlock's wording back. */
function InstructionEditor({ item, busy, onDirty, onCancel, onSave }: {
  item: CleanPlanItem; busy: boolean; onDirty: (on: boolean) => void; onCancel: () => void; onSave: (text: string | null) => void;
}) {
  const start = item.instruction ?? item.action;
  const [text, setText] = useState(start);
  const yours = item.key === null;
  return (
    <div className="mt-2 flex flex-col gap-1.5 pl-6">
      <textarea value={text} maxLength={MAX_INSTRUCTION} rows={3} autoFocus
        aria-label={yours ? "Your step, in plain words" : "The fix, in plain words"}
        onChange={(e) => { setText(e.target.value); onDirty(e.target.value.trim() !== start.trim()); }}
        className="w-full resize-y rounded-md border border-input bg-card px-2.5 py-1.5 text-[13px] outline-none focus-visible:border-accent" />
      <div className="flex flex-wrap items-center gap-1.5">
        <Button size="sm" variant="primary" disabled={busy || !text.trim() || text.trim() === start.trim()}
          onClick={() => onSave(text.trim())}>Save</Button>
        <Button size="sm" variant="ghost" onClick={onCancel}>Cancel</Button>
        {!yours && item.instruction && (
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => onSave(null)}>Reset</Button>
        )}
        <span className="ml-auto font-mono text-[11px] text-muted-foreground">{text.length}/{MAX_INSTRUCTION}</span>
      </div>
    </div>
  );
}

/** "+ Add a step": a column of the file (or the rows) and what to do, in plain words. */
function AddStep({ datasetId, busy, send, onDirty }: {
  datasetId: string; busy: boolean; send: Send; onDirty: (on: boolean) => void;
}) {
  const { data: card } = useDatacard(datasetId);
  const [open, setOpen] = useState(false);
  const [column, setColumn] = useState("");
  const [text, setText] = useState("");
  const close = () => { setOpen(false); setText(""); setColumn(""); onDirty(false); };
  if (!open) {
    return (
      <Button variant="link" size="sm" className="self-start" onClick={() => setOpen(true)}><Plus /> Add a step</Button>
    );
  }
  return (
    <div className="flex flex-col gap-2 rounded-[14px] border border-border p-3" role="group" aria-label="Add a step">
      <label className="flex flex-col gap-1 text-[12px] text-muted-foreground">
        Column
        <select value={column} onChange={(e) => setColumn(e.target.value)}
          className="h-8 rounded-md border border-input bg-card px-2 font-mono text-[13px] text-foreground">
          <option value="">Rows</option>
          {(card?.columns ?? []).map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-[12px] text-muted-foreground">
        What to do
        <textarea value={text} maxLength={MAX_INSTRUCTION} rows={2} placeholder="Trim spaces and use title case"
          onChange={(e) => { setText(e.target.value); onDirty(!!e.target.value.trim()); }}
          className="w-full resize-y rounded-md border border-input bg-card px-2.5 py-1.5 text-[13px] text-foreground outline-none focus-visible:border-accent" />
      </label>
      <div className="flex justify-end gap-1.5">
        <Button size="sm" variant="ghost" onClick={close}>Cancel</Button>
        <Button size="sm" variant="primary" disabled={busy || !text.trim()}
          onClick={() => send([{ op: "add", column: column || null, instruction: text.trim() }], close)}>Add</Button>
      </div>
    </div>
  );
}
