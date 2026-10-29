// The cleaning plan (App Flow §4, UI brief §5.3a, PRD CLEAN-8a): what Clean with AI will try on the current
// version, diagnosed by Sherlock's code detectors, grouped by severity level (PRD CLEAN-8c), every fix ticked
// but those worth a look. Each shows the review's reason in muted text, or "(default level)" when code's
// default stands; "Reviewing…" while the review runs. The user unticks what they don't want (a fix, or a
// whole level), rewrites a fix in plain words (✎), adds steps of their own (PRD CLEAN-8b) or asks the chat
// to do any of that, then starts. Leakage and ID columns are info rows under "Marked, not changed".
// While it's open, the chat bar sends its `plan_id`, so chat can change it.
// From the offer it fills the centre (`layout="centre"`); from the grid it replaces Changes in the right
// panel (`layout="side"`), with the scope radios, so the grid stays visible. A plan opened for some rows
// (the new-rows toast's "Clean them", chat's "clean these rows") starts on those rows (PRD CLEAN-1).
// An ambiguous-dates fix asks which order its dates are written in, with three values read both ways
//; dates that every one reads both ways are cleaned only once the order is picked.
import { useIsMutating } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Flag, Loader2, Pencil, Plus, Sparkles, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { makeSelection } from "@/api/csv";
import { readDay, siteOf } from "@/api/columnNotes";
import {
  stalePlan, useCleanPlan, useDatacard, useDetectorLabel, useDetectors, useDiscardPlan, useEditRule, usePlanOps, useRuleStatus,
  useStartCleaning,
  type CleanScope,
} from "@/api/queries";
import type {
  CleanPlan, CleanPlanItem, Dataset, Evidence, Issue, Level, PlanOp, PlanScope, RuleIn, RuleKind, Suggestion,
} from "@/api/types";
import { displayName } from "@/components/library/LibraryPanel";
import { useSettingsOpen } from "@/components/shell/SettingsDialog";
import { Button } from "@/components/ui/button";
import { Dot, Pill, type Tone } from "@/components/ui/pill";
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

// Display order: your steps, the five levels most severe first (`cleaning/levels.py` HEADINGS), then the
// columns that are never changed.
type Group = "yours" | Level | "kept";
const GROUPS: [Group, string][] = [
  ["yours", "Your steps"],
  ["breaks", "Breaks answers"],
  ["skews", "Skews answers"],
  ["splits", "Splits groups"],
  ["check", "Worth a look"],
  ["cosmetic", "Cosmetic"],
  ["kept", "Marked, not changed"],
];

// Each group's dot: red what breaks answers, amber what skews or splits them, blue what's worth a look.
const GROUP_TONE: Record<Group, Tone> = {
  yours: "teal", breaks: "red", skews: "amber", splits: "amber", check: "blue", cosmetic: "neutral", kept: "neutral",
};

export function groupOf(i: CleanPlanItem): Group {
  if (i.module === "yours" || i.module === "kept") return i.module;
  return i.sev ?? "check";
}
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
    ? "mx-auto flex h-full w-full max-w-[720px] flex-col px-6 pt-8"
    : "flex h-full flex-col";
  if (!plan || plan.status !== "draft") {
    return (
      <div className={shell}>
        <div className={cn("flex items-center gap-3", layout === "centre" ? "m-auto" : "p-5")} role="status">
          <span className="inline-flex size-9 items-center justify-center rounded-full bg-violet-soft" aria-hidden>
            <Loader2 className="size-4 animate-spin text-violet" />
          </span>
          <p className={layout === "centre" ? "type-title" : "text-[14px]"}>
            {creating || dataset.clean_plan_id ? `Looking through ${displayName(dataset.name)}…` : "No cleaning plan open."}
          </p>
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
    () => GROUPS.map(([g, title]) => ({
      group: g, title,
      // Within a level, the biggest by code severity first; your steps keep their order.
      items: plan.items.filter((i) => groupOf(i) === g).sort((a, b) => g === "yours" ? 0 : (b.severity ?? 0) - (a.severity ?? 0)),
    })).filter((g) => g.items.length),
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
      const ticked = plan.items.filter((i) => i.change && i.ticked).map((i) => i.id);
      await start.mutateAsync({ plan_id: plan.id, scope: s, ticked });
      if (side) toast("Cleaning started. Its steps appear in Changes as they commit.");
    } catch (e) {
      if (stalePlan(e)) toast((e as Error).message);
      else toast.error((e as Error).message);
    }
  };

  return (
    <section aria-labelledby="plan-title" className="flex min-h-0 flex-1 flex-col">
      <header className={cn("shrink-0", side ? "px-5 pb-3 pt-4" : "pb-5")}>
        <div className="flex items-center gap-2">
          <h2 id="plan-title" className={side ? "type-heading" : "type-display"}>Cleaning plan</h2>
          {plan.review === "running" && <Pill tone="violet" size="sm" className="ml-auto" icon={<Loader2 className="animate-spin" aria-hidden />}><span role="status">Reviewing…</span></Pill>}
        </div>
        <p className={cn("text-muted-foreground", side ? "mt-1 text-[13px]" : "mt-1.5 text-[14px]")}>
          {plan.version < dataset.current_version
            // A new version arrived while the plan was open; reading it again merges it onto that version.
            ? "The data changed since this plan was made. Updating it…"
            : "Untick what you don't want, edit a fix, or ask in chat."}
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

      <div className={cn("flex min-h-0 flex-1 flex-col overflow-y-auto", side ? "gap-4 px-5 pb-4" : "gap-6 pb-6")}>
      {side && (
        <fieldset className="flex flex-col gap-1.5 text-[13px]">
          <legend className="mb-1.5 type-label">Scope</legend>
          {([
            ...(preset ? [["preset", presetLabel(preset)] as const] : []),
            ["all", "Whole dataset"],
            ["selection", `Current selection (${selected.toLocaleString()} rows)`],
            ["new_rows", "Rows added since the last clean"],
          ] as const).map(([v, label]) => (
            <label key={v} className={cn("flex items-center gap-2", v === "selection" && selected === 0 && "opacity-40")}>
              <input type="radio" name="plan-scope" checked={scope === v} disabled={v === "selection" && selected === 0}
                onChange={() => setScope(v)} />
              {label}
            </label>
          ))}
          {scope !== "all" && (
            <p className="text-[12px] text-muted-foreground">Counts are for the whole file; changes stay inside the rows in scope.</p>
          )}
        </fieldset>
      )}

      <div className={cn("flex flex-col", side ? "gap-4" : "gap-6")}>
        {groups.map((g) => (
          <PlanGroup key={g.group} group={g.group} title={g.title} items={g.items} side={side} busy={ops.isPending}
            send={send} onDirty={markDirty} planId={plan.id}
            onTickAll={(on) => send([g.group === "yours"
              ? { op: on ? "tick_module" : "untick_module", module: "yours" }
              : { op: on ? "tick_level" : "untick_level", level: g.group as Level }])} />
        ))}
        {!!plan.suggestions?.length && (
          <SuggestedChecks items={plan.suggestions} busy={ops.isPending} send={send} planId={plan.id}
            onDirty={(on) => markDirty("suggestion", on)} />
        )}
        {!changeable.length && <p className="text-[14px] text-muted-foreground">Nothing needs cleaning yet. Add a step of your own below.</p>}
        <div className="flex flex-wrap gap-2">
          <AddStep datasetId={dataset.id} busy={ops.isPending} send={send} onDirty={(on) => markDirty("add", on)} />
          <AddCheck datasetId={dataset.id} busy={ops.isPending} send={send} onDirty={(on) => markDirty("check", on)} />
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <span className="type-label">Mode</span>
        <div role="radiogroup" aria-label="Mode" className="flex flex-wrap items-center gap-x-5 gap-y-1.5 text-[13px]">
          <label className="flex items-center gap-2">
            <input type="radio" name={`plan-mode-${layout}`} checked readOnly /> Run on its own
          </label>
          <label className="flex items-center gap-2 text-muted-foreground" title="Step-by-step cleaning comes in a later release">
            <input type="radio" name={`plan-mode-${layout}`} disabled /> Ask me before each fix <Pill size="sm">Soon</Pill>
          </label>
        </div>
      </div>
      </div>

      <footer className={cn("flex shrink-0 flex-col gap-2.5 border-t border-border", side ? "bg-background px-5 py-3.5" : "bg-card py-4")}>
        {unsaved && (
          <div className="flex items-center gap-2 rounded-xl bg-amber-soft px-3 py-2 text-[12.5px]">
            <span className="flex-1">Save or discard your {pending} unsaved {pending === 1 ? "change" : "changes"} first.</span>
            <Button size="sm" variant="ghost" onClick={() => discardEdits(dataset.id)}>Discard edits</Button>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <p className="mr-auto text-[13px] text-muted-foreground tnum" title="Cells you edited by hand are left as they are and listed in the report.">
            {ticked} of {changeable.length} selected
            {ticked > ISSUE_BUDGET && <span className="block text-[12px]">Up to {ISSUE_BUDGET} run at a time: yours first, then the most severe.</span>}
          </p>
          <Button variant="ghost" size={side ? "sm" : "default"} loading={discard.isPending}
            onClick={() => discard.mutate(plan.id, { onError: (e) => toast.error((e as Error).message) })}>Discard</Button>
          <Button variant="ai" size={side ? "sm" : "default"} loading={start.isPending}
            disabled={ticked === 0 || unsaved || editing || ops.isPending} onClick={begin}
            title={ticked === 0 ? "Tick at least one fix" : unsaved ? "Save or discard your edits first"
              : editing ? "Save or cancel the step you're editing first" : undefined}>
            {!start.isPending && <Sparkles aria-hidden />}
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
            className={cn("h-7 rounded-full border px-3 text-[12.5px] font-medium",
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

function PlanGroup({ group, title, items, side, busy, send, onDirty, onTickAll, planId }: {
  group: Group; title: string; items: CleanPlanItem[]; side: boolean; busy: boolean;
  send: Send; onDirty: (id: string, on: boolean) => void; onTickAll: (on: boolean) => void; planId: string;
}) {
  const kept = group === "kept";
  const on = items.filter((i) => i.ticked).length;
  const box = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (box.current) box.current.indeterminate = on > 0 && on < items.length;
  }, [on, items.length]);
  const headingId = `plan-group-${group}`;
  return (
    <section aria-labelledby={headingId}>
      <div className="flex items-center gap-2.5 border-b border-border pb-2">
        {!kept && (
          <input ref={box} type="checkbox" checked={on === items.length} disabled={busy}
            aria-label={`${title}: tick all`} onChange={(e) => onTickAll(e.target.checked)} />
        )}
        <Dot tone={GROUP_TONE[group]} />
        <h3 id={headingId} className="text-[13px] font-semibold tracking-[-0.01em]">{title}</h3>
        {!kept && <Pill size="sm" className="ml-auto">{on} of {items.length}</Pill>}
      </div>
      <ul className="flex flex-col">
        {items.map((i) => <ItemRow key={i.id} item={i} side={side} busy={busy} send={send} onDirty={(on) => onDirty(i.id, on)}
          planId={planId} />)}
      </ul>
    </section>
  );
}

function ItemRow({ item, side, busy, send, onDirty, planId }: {
  item: CleanPlanItem; side: boolean; busy: boolean; send: Send; onDirty: (on: boolean) => void; planId: string;
}) {
  const ruleStatus = useRuleStatus(planId);
  const ruleId = item.detector.startsWith("rule:") ? item.detector.slice("rule:".length) : null;
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const label = useDetectorLabel()(item.detector);
  const name = `${item.column ?? "rows"}: ${label}`;
  const yours = item.key === null;
  const onTick = (on: boolean) => send([{ op: on ? "tick" : "untick", item_id: item.id }]);
  return (
    <li className="border-b border-border py-3 last:border-b-0">
      <div className="flex items-start gap-2.5">
        {item.change ? (
          <input type="checkbox" checked={item.ticked} disabled={busy} aria-label={name} onChange={(e) => onTick(e.target.checked)}
            className="mt-1 shrink-0" />
        ) : (
          <Flag className="mt-0.5 size-4 shrink-0 text-amber" aria-hidden />
        )}
        <div className={cn("min-w-0 flex-1", !side && "flex flex-wrap items-center gap-x-2.5 gap-y-0.5")}>
          <span className="type-data font-medium">{item.column ?? "rows"}</span>{" "}
          <span className={cn("text-[14px]", !item.ticked && item.change && "text-muted-foreground")}>{label}</span>
          {item.count !== null && <Pill size="sm" className="ml-1.5 align-[1px]">{item.count.toLocaleString()}</Pill>}
          {!item.change ? (
            <p className={cn("text-[13px] text-muted-foreground", !side && "basis-full")}>{item.reason}</p>
          ) : item.instruction && !yours ? (
            <div className={cn("text-[13px]", !side && "basis-full")}>
              <p>{item.instruction} <Pill tone="violet" size="sm" className="ml-1">edited</Pill></p>
              <p className="text-muted-foreground line-through decoration-muted-foreground/40">{item.action}</p>
            </div>
          ) : (
            <p className={cn("text-[13px]", yours ? "text-foreground" : "text-muted-foreground", !side && "basis-full")}>
              {item.action}{item.source === "chat" && <Pill tone="blue" size="sm" className="ml-1.5">from chat</Pill>}
            </p>
          )}
          {item.evidence && <EvidenceLine evidence={item.evidence} className={cn(!side && "basis-full")} />}
          {item.change && !yours && item.sev_reason && (
            <p className={cn("text-[12px] text-muted-foreground", !side && "basis-full")}>{item.sev_reason}</p>
          )}
        </div>
        {item.change && !editing && (
          <button type="button" onClick={() => setEditing(true)} disabled={busy}
            aria-label={yours ? `Edit your step on ${item.column ?? "the rows"}` : `Rewrite the fix for ${name}`}
            className="mt-0.5 shrink-0 rounded p-0.5 text-muted-foreground hover:bg-secondary hover:text-foreground">
            <Pencil className="size-3.5" />
          </button>
        )}
        {ruleId && (
          <button type="button" disabled={busy || ruleStatus.isPending}
            onClick={() => ruleStatus.mutate({ ruleId, status: "off" }, { onError: (e) => toast.error((e as Error).message) })}
            aria-label={`Turn off your check on ${item.column ?? "the rows"}`}
            className="mt-0.5 shrink-0 rounded p-0.5 text-muted-foreground hover:bg-secondary hover:text-foreground">
            <X className="size-3.5" />
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
        <ul className="mt-2 flex flex-wrap gap-1.5 pl-6" aria-label={`Examples of ${name}`}>
          {item.examples.map((v, n) => (
            <li key={n} className="max-w-[240px] truncate rounded-full bg-secondary px-2.5 py-0.5 type-data text-[12px]">
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
// "Suggested checks" (PRD CLEAN-14): rules Sherlock wrote, counted by code, run only once kept.
function SuggestedChecks({ items, busy, send, planId, onDirty }: {
  items: Suggestion[]; busy: boolean; send: Send; planId: string; onDirty: (on: boolean) => void;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  return (
    <section aria-labelledby="plan-group-suggested">
      <div className="flex items-center gap-2.5 border-b border-border pb-2">
        <Dot tone="violet" />
        <h3 id="plan-group-suggested" className="text-[13px] font-semibold tracking-[-0.01em]">
          Suggested checks
        </h3>
      </div>
      <ul className="flex flex-col">
        {items.map((s) => (
          <li key={s.id} className="flex items-start gap-2.5 border-b border-border py-3 last:border-b-0">
            <input type="checkbox" checked={false} disabled aria-label={`${s.words}: not run until kept`}
              className="mt-1 shrink-0" />
            <div className="min-w-0 flex-1 text-[14px]">
              <span>{s.words}</span>
              {s.evidence ? (
                <EvidenceLine evidence={s.evidence} />
              ) : (
                <Pill tone="violet" size="sm" className="ml-1.5">suggested by Sherlock</Pill>
              )}
              <p className="text-[13px] text-muted-foreground">
                {s.error ?? (s.count === 1 ? "1 row breaks it." : `${(s.count ?? 0).toLocaleString()} rows break it.`)}
                {s.reason && <span className="ml-1.5">{s.reason}</span>}
              </p>
            </div>
            <Button size="sm" variant="ghost" disabled={busy || editing === s.id} aria-label={`Edit ${s.words}`}
              onClick={() => setEditing(s.id)}>
              Edit
            </Button>
            <Button size="sm" variant="secondary" disabled={busy} onClick={() => send([{ op: "keep_suggestion", rule_id: s.id }])}>
              Keep
            </Button>
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => send([{ op: "dismiss_suggestion", rule_id: s.id }])}>
              Dismiss
            </Button>
          </li>
        ))}
      </ul>
      {editing && (
        <SuggestionEditor key={editing} suggestion={items.find((s) => s.id === editing)!} planId={planId}
          onDirty={onDirty} onDone={() => { onDirty(false); setEditing(null); }} />
      )}
    </section>
  );
}

/** Where a check's numbers came from (docs/plans/tavily.md §3.3), for a suggested check or a kept one: the page's
 * domain as a link, the page's own words in a quote (two lines; the whole quote is in its title), and the day read. */
function EvidenceLine({ evidence, className }: { evidence: Evidence; className?: string }) {
  return (
    <div className={cn("mt-0.5 min-w-0", className)}>
      <p className="text-[12px]">
        <a href={evidence.url} target="_blank" rel="noopener noreferrer" title={evidence.title}
          className="text-accent hover:underline">From {siteOf(evidence.url)}</a>
        <span className="text-muted-foreground"> · read {readDay(evidence.retrieved_at)}</span>
      </p>
      <blockquote title={evidence.excerpt} className="mt-0.5 line-clamp-2 border-l-2 border-border pl-2 text-[12.5px] italic text-foreground-2">
        “{evidence.excerpt}”
      </blockquote>
    </div>
  );
}

/** A suggestion's values as the Add a check fields hold them (`ruleParams` reads them back). */
export function fieldsOf(kind: RuleKind, params: Record<string, unknown>): Record<string, string> {
  const s = (v: unknown) => (v === null || v === undefined ? "" : String(v));
  switch (kind) {
    case "range": return { min: s(params.min), max: s(params.max) };
    case "date_window": return { min: s(params.earliest), max: s(params.latest) };
    case "allowed": return { values: ((params.values as string[]) ?? []).join(", ") };
    case "pattern": return { values: s(params.regex) };
    case "order": return { other: s(params.left) };
    case "depends": return { other: s(params.from) };
    default: return {};
  }
}

/** Edit a suggested check's values before keeping it (PRD CLEAN-14): the thresholds are suggestions. */
function SuggestionEditor({ suggestion, planId, onDirty, onDone }: {
  suggestion: Suggestion; planId: string; onDirty: (on: boolean) => void; onDone: () => void;
}) {
  const edit = useEditRule(planId);
  const [f, setF] = useState<Record<string, string>>(() => fieldsOf(suggestion.kind, suggestion.params));
  const [action, setAction] = useState<RuleIn["action"]>(suggestion.action);
  const set = (k: string, v: string) => { setF((x) => ({ ...x, [k]: v })); onDirty(true); };
  const field = (k: string, label: string) => (
    <label className="flex flex-col gap-1 text-[12px] text-muted-foreground">
      {label}
      <input value={f[k] ?? ""} onChange={(e) => set(k, e.target.value)}
        className="h-8 rounded-md border border-input bg-card px-2 text-[13px] text-foreground" />
    </label>
  );
  const kind = suggestion.kind;
  return (
    <div className="mt-2 flex flex-col gap-2 rounded-2xl bg-background p-4" role="group" aria-label={`Edit ${suggestion.words}`}>
      {kind === "range" && <div className="flex gap-2">{field("min", "Lowest")}{field("max", "Highest")}</div>}
      {kind === "date_window" && <div className="flex gap-2">{field("min", "Earliest")}{field("max", "Latest")}</div>}
      {kind === "allowed" && field("values", "Allowed values, separated by commas")}
      {kind === "pattern" && field("values", "Pattern")}
      {(kind === "order" || kind === "depends") && field("other", kind === "order" ? "After the column" : "Set by the column")}
      <label className="flex flex-col gap-1 text-[12px] text-muted-foreground">
        Rows that break it
        <select value={action} onChange={(e) => { setAction(e.target.value as RuleIn["action"]); onDirty(true); }}
          className="h-8 rounded-md border border-input bg-card px-2 text-[13px] text-foreground">
          {ACTIONS.map(([a, label]) => <option key={a} value={a}>{label}</option>)}
        </select>
      </label>
      <div className="flex justify-end gap-1.5">
        <Button size="sm" variant="ghost" onClick={onDone}>Cancel</Button>
        <Button size="sm" variant="primary" loading={edit.isPending}
          onClick={() => edit.mutate({ ruleId: suggestion.id, params: ruleParams(kind, f), action },
                                      { onSuccess: onDone, onError: (e) => toast.error((e as Error).message) })}>
          Save
        </Button>
      </div>
    </div>
  );
}

// "Add a check" (PRD CLEAN-13): a rule code runs on every version; its count shows as soon as it's saved.
const KINDS: [RuleKind, string][] = [
  ["range", "Numbers between"], ["date_window", "Dates between"], ["allowed", "One of these values"],
  ["pattern", "Matches a pattern"], ["not_missing", "Never missing"], ["unique", "Never repeated"],
  ["order", "Comes after another column"], ["depends", "Set by another column"],
];
const ACTIONS: [RuleIn["action"], string][] = [
  ["flag", "Flag the rows for review"], ["quarantine", "Quarantine the rows"], ["fix", "Fix the values"],
];

export function ruleParams(kind: RuleKind, f: Record<string, string>): Record<string, unknown> {
  const num = (v: string) => (v.trim() === "" ? null : Number(v));
  switch (kind) {
    case "range": return { min: num(f.min ?? ""), max: num(f.max ?? "") };
    case "date_window": return { earliest: f.min || null, latest: f.max || null };
    case "allowed": return { values: (f.values ?? "").split(",").map((v) => v.trim()).filter(Boolean) };
    case "pattern": return { regex: f.values ?? "" };
    case "order": return { left: f.other ?? "", op: "<" };
    case "depends": return { from: f.other ?? "" };
    default: return {};
  }
}

function AddCheck({ datasetId, busy, send, onDirty }: {
  datasetId: string; busy: boolean; send: Send; onDirty: (on: boolean) => void;
}) {
  const { data: card } = useDatacard(datasetId);
  const [open, setOpen] = useState(false);
  const [column, setColumn] = useState("");
  const [kind, setKind] = useState<RuleKind>("range");
  const [action, setAction] = useState<RuleIn["action"]>("flag");
  const [everywhere, setEverywhere] = useState(false);
  const [f, setF] = useState<Record<string, string>>({});
  const close = () => { setOpen(false); setColumn(""); setF({}); setEverywhere(false); onDirty(false); };
  const set = (k: string, v: string) => { setF((x) => ({ ...x, [k]: v })); onDirty(true); };
  const columns = card?.columns ?? [];
  if (!open) {
    return <Button variant="secondary" size="sm" className="self-start" onClick={() => setOpen(true)}><Plus /> Add a check</Button>;
  }
  const field = (k: string, label: string, placeholder = "") => (
    <label className="flex flex-col gap-1 text-[12px] text-muted-foreground">
      {label}
      <input value={f[k] ?? ""} placeholder={placeholder} onChange={(e) => set(k, e.target.value)}
        className="h-8 rounded-md border border-input bg-card px-2 text-[13px] text-foreground" />
    </label>
  );
  const pick = (k: string, label: string) => (
    <label className="flex flex-col gap-1 text-[12px] text-muted-foreground">
      {label}
      <select value={f[k] ?? ""} onChange={(e) => set(k, e.target.value)}
        className="h-8 rounded-md border border-input bg-card px-2 font-mono text-[13px] text-foreground">
        <option value="">Choose a column</option>
        {columns.filter((c) => c.name !== column).map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
      </select>
    </label>
  );
  return (
    <div className="flex w-full flex-col gap-2 rounded-2xl bg-background p-4" role="group" aria-label="Add a check">
      <label className="flex flex-col gap-1 text-[12px] text-muted-foreground">
        Column
        <select value={column} onChange={(e) => { setColumn(e.target.value); onDirty(true); }}
          className="h-8 rounded-md border border-input bg-card px-2 font-mono text-[13px] text-foreground">
          <option value="">Choose a column</option>
          {columns.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-[12px] text-muted-foreground">
        Check
        <select value={kind} onChange={(e) => { setKind(e.target.value as RuleKind); setF({}); }}
          className="h-8 rounded-md border border-input bg-card px-2 text-[13px] text-foreground">
          {KINDS.map(([k, label]) => <option key={k} value={k}>{label}</option>)}
        </select>
      </label>
      {kind === "range" && <div className="flex gap-2">{field("min", "Lowest")}{field("max", "Highest")}</div>}
      {kind === "date_window" && <div className="flex gap-2">{field("min", "Earliest", "YYYY-MM-DD")}{field("max", "Latest", "YYYY-MM-DD")}</div>}
      {kind === "allowed" && field("values", "Allowed values, separated by commas")}
      {kind === "pattern" && field("values", "Pattern", "^[A-Z]{2}-[0-9]+$")}
      {kind === "order" && pick("other", "After the column")}
      {kind === "depends" && pick("other", "Set by the column")}
      <label className="flex flex-col gap-1 text-[12px] text-muted-foreground">
        Rows that break it
        <select value={action} onChange={(e) => setAction(e.target.value as RuleIn["action"])}
          className="h-8 rounded-md border border-input bg-card px-2 text-[13px] text-foreground">
          {ACTIONS.map(([a, label]) => <option key={a} value={a}>{label}</option>)}
        </select>
      </label>
      <label className="flex items-center gap-2 text-[12.5px]">
        <input type="checkbox" checked={everywhere} onChange={(e) => setEverywhere(e.target.checked)}
          />
        For every dataset of mine
      </label>
      <div className="flex justify-end gap-1.5">
        <Button size="sm" variant="ghost" onClick={close}>Cancel</Button>
        <Button size="sm" variant="primary" disabled={busy || !column}
          onClick={() => send([{ op: "add_rule", rule: { kind, column, params: ruleParams(kind, f), action,
                                                         scope: everywhere ? "all" : "dataset" } }], close)}>
          Add check
        </Button>
      </div>
    </div>
  );
}

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
      <Button variant="secondary" size="sm" className="self-start" onClick={() => setOpen(true)}><Plus /> Add a step</Button>
    );
  }
  return (
    <div className="flex flex-col gap-2 rounded-2xl bg-background p-4" role="group" aria-label="Add a step">
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
