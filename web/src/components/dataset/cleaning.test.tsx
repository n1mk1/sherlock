import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { Toaster } from "sonner";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useDataset } from "@/api/queries";
import type { CleanPlan, CleanPlanItem, Dataset, JobLogEntry } from "@/api/types";
import { SaveActions } from "@/components/csv/SaveActions";
import { CsvSidePanel } from "@/components/shell/AppShell";
import { ProposalView } from "@/components/shell/ChatBar";
import { useEdits } from "@/state/edits";
import { useUi } from "@/state/ui";
import { ME, mockApi, renderAt } from "@/test/render";
import { CleanPlanPanel, DateOrder } from "./CleanPlanPanel";
import { callsLine, CleaningProgress, collapse, LogEntry, mergeLog, mmss } from "./CleaningProgress";
import { ReportSummary } from "./CleaningReport";
import { CleaningOffer, summaryLines } from "./CleaningOffer";
import { OfferActions } from "./OfferActions";

afterEach(() => vi.unstubAllGlobals());

const DS = {
  id: "ds_1", name: "messy.csv", status: "offer", current_version: 2, row_count: 120, column_count: 4,
  created_at: "", last_opened_at: null, last_tab: null, error: null,
} as Dataset;

describe("cleaning screens", () => {
  it("merges a running line with its outcome", () => {
    const base = { job_id: "j", ts: "2026-10-24T00:00:00Z", level: "info" };
    const entries: JobLogEntry[] = [
      { ...base, icon: "running", text: "263 missing values", column: "age", issue_id: "i1", detail: "checking candidates" },
      { ...base, icon: "check", text: "Fills ages by title", column: "age", issue_id: "i1", gate: "commit", detail: "committed · step 2" },
      { ...base, icon: "skip", text: "Looks like an ID column", column: "name", issue_id: "i2" },
    ];
    const out = collapse(entries);
    expect(out).toHaveLength(2);
    expect(out[0]).toMatchObject({ text: "263 missing values", outcome: "Fills ages by title", gate: "commit" });
    expect(mmss(83)).toBe("01:23");
  });

  it("merges a running line with its outcome across a wait for the model", () => {
    const base = { job_id: "j", ts: "2026-10-24T00:00:00Z", level: "info" };
    const entries: JobLogEntry[] = [
      { ...base, icon: "running", text: "263 missing values", column: "age", issue_id: "i1", detail: "checking candidates" },
      { ...base, icon: "wait", text: "Waiting for the model…", level: "warn" },
      { ...base, icon: "check", text: "Fills ages by title", column: "age", issue_id: "i1", gate: "commit", detail: "committed · step 2" },
    ];
    const out = collapse(entries);
    expect(out.map((e) => e.icon)).toEqual(["check", "wait"]);
    expect(out[0]).toMatchObject({ text: "263 missing values", outcome: "Fills ages by title" });
  });

  it("shows a step's line from its report, the model's note and the issue's model calls", () => {
    const base = { job_id: "j", ts: "2026-10-24T00:00:00Z", level: "info" };
    const calls = { count: 3, models: ["nvidia/Nemotron-3-Ultra", "nvidia/nemotron-3-super"], latency_ms: 12345 };
    const [entry] = collapse([
      { ...base, icon: "running", text: "263 missing values", column: "age", issue_id: "i1" },
      { ...base, icon: "check", text: "Changed 263 cells; 263 → 0 missing values", column: "age", issue_id: "i1", gate: "commit",
        detail: "committed · step 2", note: "Fills each age from its group.", calls },
    ]);
    renderAt(<ol><LogEntry entry={entry} started={Date.parse(base.ts)} /></ol>);
    expect(screen.getByText("Changed 263 cells; 263 → 0 missing values")).toBeInTheDocument();
    expect(screen.getByText("Fills each age from its group.")).toBeInTheDocument();
    expect(screen.getByText("3 model calls · Nemotron-3-Ultra, nemotron-3-super · 12.3 s")).toBeInTheDocument();
    expect(callsLine({ count: 1, models: ["nvidia/x"], latency_ms: 800 })).toBe("1 model call · x · 0.8 s");
  });

  it("loads the log so far from the job's own log and keeps each line once", async () => {
    const base = { job_id: "job_1", level: "info", icon: "check" };
    const first = { ...base, ts: "2026-10-24T00:00:01Z", text: "Trimmed spaces in name" };
    const second = { ...base, ts: "2026-10-24T00:00:02Z", text: "Filled age by title" };
    expect(mergeLog([second], [first, second]).map((e) => e.text)).toEqual(["Trimmed spaces in name", "Filled age by title"]);
    const fetchMock = mockApi({
      "GET /api/v1/jobs": [{ id: "job_1", dataset_id: "ds_1", kind: "clean", status: "running", created_at: "",
                             started_at: "2026-10-24T00:00:00Z", finished_at: null, error: null, result: null,
                             progress: { step: 2, of: 5, label: "Fixing age", pct: 20 } }],
      "GET /api/v1/jobs/job_1/log": { entries: [first, second] },
      "GET /api/v1/datasets/ds_1/report": new Response(JSON.stringify({ error: { code: "not_found", message: "none" } }), { status: 404 }),
    });
    renderAt(<CleaningProgress dataset={{ ...DS, status: "cleaning" }} />);
    expect(await screen.findByText("Trimmed spaces in name")).toBeInTheDocument();
    expect(screen.getByText("Filled age by title")).toBeInTheDocument();
    expect(screen.getByText("Fixing age")).toBeInTheDocument(); // the job's own progress before the stream's first event
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes("/api/v1/jobs/job_1/log"))).toBe(true);
  });

  it("Clean with AI makes the plan and can remember the choice", async () => {
    const calls = mockApi({
      "POST /api/v1/datasets/ds_1/clean/plan": PLAN,
      "PUT /api/v1/me/settings": ME.settings,
      "GET /api/v1/datasets/ds_1": DS,
    });
    renderAt(<OfferActions dataset={DS} depth={2} />);
    fireEvent.click(screen.getByLabelText("Remember my choice"));
    fireEvent.click(screen.getByRole("button", { name: "Clean with AI" }));
    await waitFor(() => expect(sent(calls).some((c) => c.path.endsWith("/clean/plan") && c.method === "POST")).toBe(true));
    const made = sent(calls).find((c) => c.path.endsWith("/clean/plan"));
    expect(made?.body).toEqual({ depth: 2 }); // the slider's depth (PRD CLEAN-15)
    const put = calls.mock.calls.find(([u]) => String((u as Request).url ?? u).includes("/me/settings"));
    expect(await (put?.[0] as Request).json()).toEqual({ after_upload: "always", clean_depth: 2 });
    expect(sent(calls).some((c) => c.path.endsWith("/clean"))).toBe(false); // nothing is cleaned yet
    expect(screen.queryByRole("button", { name: "Go step by step" })).toBeNull();
    expect(screen.getByText("· You can change this in Settings")).toBeInTheDocument();
  });

  it("Clean it myself makes the dataset ready as it is, so its page shows the grid", async () => {
    const calls = mockApi({
      "GET /api/v1/datasets/ds_1": DS,
      "POST /api/v1/datasets/ds_1/use-as-is": { ...DS, status: "ready" },
    });
    function Status() {
      return <p>status: {useDataset("ds_1").data?.status}</p>;
    }
    renderAt(<><OfferActions dataset={DS} /><Status /></>);
    fireEvent.click(screen.getByRole("button", { name: "Clean it myself" }));
    expect(await screen.findByText("status: ready")).toBeInTheDocument(); // the answer is the dataset, cached at once
    expect(sent(calls).map((c) => c.path)).toContain("/api/v1/datasets/ds_1/use-as-is");
  });

  it("leads with never-changed columns, then the most severe issues by level, then by size", () => {
    const i = (id: string, level: string | null, severity: number) =>
      ({ id, detector: "missing", column: id, count: 1, severity, proposal: "", examples: [], details: {}, level });
    const card = { issues: [i("big_check", "check", 0.9), i("skews", "skews", 0.1), i("breaks", "breaks", 0.05),
                            i("kept", null, 1.0), i("splits", "splits", 0.2)] } as never;
    expect(summaryLines(card).map((x) => x.id)).toEqual(["kept", "breaks", "skews"]);
    const old = { issues: [i("a", null, 0.1), i("b", null, 0.5)] } as never;  // a card from before levels
    expect(summaryLines(old).map((x) => x.id)).toEqual(["b", "a"]);
  });

  it("shows only the issues down to the depth the slider picks", async () => {
    const issue = (id: string, detector: string, count: number) =>
      ({ id, detector, column: "amount", count, severity: 0.5, proposal: "", examples: [], details: {} });
    mockApi({
      "GET /api/v1/me": ME,
      "GET /api/v1/datasets/ds_1/datacard": { version: 2, row_count: 120, column_count: 4, quarantined: 0, columns: [],
        issues: [issue("a", "sentinels", 3), issue("b", "duplicates", 4), issue("c", "cross_column", 5)] },
    });
    renderAt(<CleaningOffer dataset={DS} actions={(depth) => <span>picked {depth}</span>} />);
    expect(await screen.findByText(/3 issues/)).toBeInTheDocument(); // the setting's depth: every layer
    const slider = await screen.findByRole("slider", { name: "Cleaning depth" });
    fireEvent.change(slider, { target: { value: "1" } });
    expect(screen.getByText(/1 issue · 2 more in deeper layers/)).toBeInTheDocument();
    expect(screen.getByText("3 placeholder values in amount")).toBeInTheDocument();
    expect(screen.queryByText("4 duplicate rows in amount")).toBeNull();
    expect(screen.getByText("picked 1")).toBeInTheDocument();
    expect(screen.getByText(/Looks at single values: .*placeholder values/)).toBeInTheDocument();
    fireEvent.change(slider, { target: { value: "3" } });
    expect(screen.getByText(/2 issues · 1 more in deeper layers/)).toBeInTheDocument();
    expect(slider).toHaveAttribute("aria-valuetext", "Layer 3 of 5: Records");
  });

  it("offers retry choices after a failed run", () => {
    mockApi({});
    renderAt(<OfferActions dataset={{ ...DS, error: "Cleaning stopped: model unavailable" }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Cleaning stopped: model unavailable");
    expect(screen.getByRole("button", { name: "Try cleaning again" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Use as is" })).toBeInTheDocument();
  });

  it("summarizes the report", async () => {
    mockApi({
      "GET /api/v1/datasets/ds_1/report": {
        job_id: "job_1", status: "done", from_version: 2, to_version: 4, ended_by: "done", waited_for_model_s: 0,
        attempted: 4, budget: { max_steps: 20, max_seconds: 300 }, started_at: null, finished_at: null, error: null,
        counts: { found: 5, fixed: 1, flagged: 1, skipped: 3, rows_deleted: 0 },
        steps: [{ step_id: "s2", no: 2, summary: "Parse money as numbers (amount)", gate: "flag", confidence: 0.9,
                  flag_reason: "changes more than a fifth of the data",
                  impact: { cells_changed: 120, quarantined: 1, rows_added: 0, rows_deleted: 0 } }],
        skipped: [{ issue_id: "i", column: "customer_id", detector: "id_candidates", reason: "Looks like an ID column" }],
        hand_edited_skipped: [], decisions: [],
      },
    });
    renderAt(<ReportSummary datasetId="ds_1" />);
    expect(await screen.findByText("Every issue was looked at. v2 → v4")).toBeInTheDocument();
    expect(screen.getByText("Parse money as numbers (amount)")).toBeInTheDocument();
    expect(screen.getByText("changes more than a fifth of the data")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View full report" }));
    expect(await screen.findByText(/Looks like an ID column/)).toBeInTheDocument();
  });

  it("names the configured issue budget when the run hit it", async () => {
    mockApi({
      "GET /api/v1/datasets/ds_1/report": {
        job_id: "job_1", status: "done", from_version: 2, to_version: 9, ended_by: "steps", waited_for_model_s: 0,
        attempted: 12, budget: { max_steps: 12, max_seconds: 300 }, started_at: null, finished_at: null, error: null,
        counts: { found: 30, fixed: 7, flagged: 0, skipped: 5, rows_deleted: 0 },
        steps: [], skipped: [], hand_edited_skipped: [], decisions: [],
      },
    });
    renderAt(<ReportSummary datasetId="ds_1" />);
    expect(await screen.findByText("Stopped at the 12-issue budget. v2 → v9")).toBeInTheDocument();
  });

  it("says what became of each issue, and lists the skips under their lines with their levels", async () => {
    const skip = (id: string, kind: string, level: string | null, reason: string) =>
      ({ issue_id: id, column: id, detector: "missing", reason, skip_kind: kind, level });
    mockApi({
      "GET /api/v1/datasets/ds_1/report": {
        job_id: "job_1", status: "done", from_version: 2, to_version: 4, ended_by: "time", waited_for_model_s: 0,
        attempted: 4, budget: { max_steps: 20, max_seconds: 300 }, started_at: null, finished_at: null, error: null,
        counts: { found: 9, fixed: 2, flagged: 1, skipped: 4, rows_deleted: 0, checked_and_kept: 1, couldnt_fix: 1,
                  not_attempted: 3, kept_by_design: 1 },
        steps: [], hand_edited_skipped: [], decisions: [],
        skipped: [skip("cabin", "left_as_is", "check", "Left as is: the values look legitimate"),
                  skip("fare", "failed_checks", "breaks", "No candidate passed the checks"),
                  skip("notes", "unticked", "cosmetic", "You left this out of the plan"),
                  skip("code", "kept_by_design", null, "Looks like an ID column, so it is left as is")],
      },
    });
    renderAt(<ReportSummary datasetId="ds_1" />);
    const tiles = await screen.findAllByRole("term");
    expect(tiles.map((t) => t.textContent)).toEqual(["fixed", "flagged", "checked and kept", "couldn't fix", "not attempted"]);
    expect(screen.getByText("9 found · 1 marked, not changed (leakage and ID columns) · no rows deleted")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "View full report" }));
    const kept = await screen.findByRole("heading", { name: "Checked and kept" });
    expect(kept.parentElement).toHaveTextContent("cabin · Left as is: the values look legitimate · Worth a look");
    expect(screen.getByRole("heading", { name: "Couldn't fix" }).parentElement).toHaveTextContent("Breaks answers");
    expect(screen.getByRole("heading", { name: "Not attempted" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Marked, not changed" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Skipped" })).toBeNull();
  });
});

// --- the cleaning plan (PRD CLEAN-8a) -------------------------------------------------------------------

const item = (over: Partial<CleanPlanItem>): CleanPlanItem => ({
  id: "pit_x", source: "sherlock", key: "missing|age", detector: "missing", column: "age", count: 263, severity: 0.1,
  action: "Fill from a rule over related columns", instruction: null, examples: [], ticked: true, change: true, module: "missing",
  sev: "check", sev_reason: null, sev_source: "default", likely_real: false,
  ...over,
});
const PLAN: CleanPlan = {
  id: "pln_1", dataset_id: "ds_1", version: 2, status: "draft", source: "user", job_id: null, scope: null, depth: 5, created_at: "", updated_at: "",
  items: [
    item({ id: "pit_amount", key: "numbers_as_text|amount", detector: "numbers_as_text", column: "amount", count: 99, module: "types",
           examples: ["$980", "$2,000"], sev: "breaks", sev_source: "model", sev_reason: "Averages of the measure can't be read." }),
    item({ id: "pit_age", key: "missing|age", column: "age", count: 13 }),
    item({ id: "pit_fare", key: "outliers|fare", detector: "outliers", column: "fare", count: 40, module: "outliers" }),
    item({ id: "pit_age_out", key: "outliers|age", detector: "outliers", column: "age", count: 4, module: "outliers" }),
    item({ id: "pit_id", key: "id_candidates|customer_id", detector: "id_candidates", column: "customer_id", count: 120,
           module: "kept", ticked: false, change: false, reason: "Looks like an ID column, so it is left as is",
           sev: null, sev_source: null }),
  ],
};
const WITH_PLAN = { ...DS, clean_plan_id: "pln_1" } as Dataset;

function sent(calls: ReturnType<typeof mockApi>) {
  return calls.mock.calls.map(([input, init]) => {
    const req = typeof input === "object" && "url" in input ? (input as Request) : null;
    const raw = (init as RequestInit | undefined)?.body;
    return {
      path: new URL(req ? req.url : String(input), "http://localhost").pathname,
      method: (req?.method ?? (init as RequestInit | undefined)?.method ?? "GET").toUpperCase(),
      body: typeof raw === "string" ? JSON.parse(raw) : undefined,
    };
  });
}

describe("the cleaning plan", () => {
  it("asks which order ambiguous dates are in, with values read both ways", () => {
    const dates = item({ id: "pit_d", key: "ambiguous_dates|visit_date", detector: "ambiguous_dates", column: "visit_date",
      count: 36, module: "types", date_order: null, needs_order: true, both_ways: [
        { value: "03/04/2021", day_first: "3 Apr 2021", month_first: "4 Mar 2021" },
        { value: "05/06/2021", day_first: "5 Jun 2021", month_first: "6 May 2021" },
        { value: "11/12/2021", day_first: "11 Dec 2021", month_first: "12 Nov 2021" }] });
    const onPick = vi.fn();
    const { rerender } = renderAt(<DateOrder item={dates} busy={false} onPick={onPick} />);
    expect(screen.getByText("4 Mar 2021")).toBeInTheDocument();
    expect(screen.getAllByRole("row")).toHaveLength(4); // the header and three values
    expect(screen.getByText(/Sherlock won't guess/)).toBeInTheDocument();
    const group = screen.getByRole("radiogroup", { name: "Which order are these dates in?" });
    fireEvent.click(within(group).getByRole("radio", { name: "Day first" }));
    expect(onPick).toHaveBeenCalledWith("dmy");
    rerender(<DateOrder item={{ ...dates, date_order: "dmy" }} busy={false} onPick={onPick} />);
    expect(screen.getByRole("radio", { name: "Day first" })).toHaveAttribute("aria-checked", "true");
    expect(screen.queryByText(/Sherlock won't guess/)).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: "Day first" }));
    expect(onPick).toHaveBeenLastCalledWith(null); // a second click clears it
  });

  it("sends the order picked in the panel as a plan op", async () => {
    const dates = item({ id: "pit_d", key: "ambiguous_dates|visit_date", detector: "ambiguous_dates", column: "visit_date",
      count: 36, module: "types", date_order: null, needs_order: true,
      both_ways: [{ value: "03/04/2021", day_first: "3 Apr 2021", month_first: "4 Mar 2021" }] });
    const withDates = { ...PLAN, items: [dates, ...PLAN.items] };
    const calls = mockApi({
      "GET /api/v1/clean-plans/pln_1": withDates,
      "PATCH /api/v1/clean-plans/pln_1": { ...withDates, items: [{ ...dates, date_order: "mdy" }, ...PLAN.items],
                                           summary: "Set the date order of visit_date to month-first." },
    });
    renderAt(<CleanPlanPanel dataset={WITH_PLAN} layout="centre" />);
    fireEvent.click(await screen.findByRole("radio", { name: "Month first" }));
    await waitFor(() => expect(sent(calls).some((c) => c.method === "PATCH")).toBe(true));
    expect(sent(calls).find((c) => c.method === "PATCH")?.body).toEqual({ ops: [{ op: "set_date_order", item_id: "pit_d", order: "mdy" }] });
  });

  it("says it's diagnosing until the plan arrives, then shows every fix ticked", async () => {
    let answer: (v: unknown) => void = () => {};
    mockApi({ "GET /api/v1/clean-plans/pln_1": () => new Promise((r) => { answer = r; }) });
    renderAt(<CleanPlanPanel dataset={WITH_PLAN} layout="centre" />);
    expect(screen.getByRole("status")).toHaveTextContent("Diagnosing v2 of messy.csv…");
    answer(PLAN);
    expect(await screen.findByRole("heading", { name: "Cleaning plan · v2" })).toBeInTheDocument();
    for (const name of ["amount: numbers stored as text", "age: missing values", "fare: outliers", "age: outliers"]) {
      expect(screen.getByRole("checkbox", { name })).toBeChecked();
    }
    // Leakage and ID columns are info rows, with no checkbox.
    expect(screen.getByText("Looks like an ID column, so it is left as is")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: /customer_id/ })).toBeNull();
    expect(screen.getByText("4 of 4 ticked")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start cleaning (4)" })).toBeEnabled();
    expect(screen.getByRole("radio", { name: /Ask me before each fix/ })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Show examples of amount: numbers stored as text" }));
    expect(screen.getByText("$2,000")).toBeInTheDocument();
  });

  it("sends a fix's tick and a module's tick as ops", async () => {
    const calls = mockApi({
      "GET /api/v1/clean-plans/pln_1": PLAN,
      "PATCH /api/v1/clean-plans/pln_1": (_: URL, init?: RequestInit) => {
        const ops = JSON.parse(String(init?.body)).ops as { op: string }[];
        const off = ops[0].op === "untick_level" ? ["pit_age", "pit_fare", "pit_age_out"] : ["pit_age"];
        return { ...PLAN, items: PLAN.items.map((i) => (off.includes(i.id) ? { ...i, ticked: false } : i)) };
      },
    });
    renderAt(<CleanPlanPanel dataset={WITH_PLAN} layout="centre" />);
    fireEvent.click(await screen.findByRole("checkbox", { name: "age: missing values" }));
    await waitFor(() => expect(screen.getByRole("checkbox", { name: "age: missing values" })).not.toBeChecked());
    expect(sent(calls).find((c) => c.method === "PATCH")?.body).toEqual({ ops: [{ op: "untick", item_id: "pit_age" }] });
    // A level's box ticks or unticks every fix of that level (PRD CLEAN-8c); with one unticked, it ticks them all.
    await waitFor(() => expect(screen.getByRole("checkbox", { name: "Worth a look: tick all" })).toBeEnabled());
    fireEvent.click(screen.getByRole("checkbox", { name: "Worth a look: tick all" }));
    await waitFor(() => expect(sent(calls).filter((c) => c.method === "PATCH")).toHaveLength(2));
    expect(sent(calls).filter((c) => c.method === "PATCH")[1].body).toEqual({ ops: [{ op: "tick_level", level: "check" }] });
  });

  it("adds a check of your own as a plan op, with its parameters", async () => {
    const calls = mockApi({
      "GET /api/v1/clean-plans/pln_1": PLAN,
      "GET /api/v1/datasets/ds_1/datacard": { columns: [{ name: "amount", type: "float" }, { name: "age", type: "float" }] },
      "PATCH /api/v1/clean-plans/pln_1": PLAN,
    });
    renderAt(<CleanPlanPanel dataset={WITH_PLAN} layout="centre" />);
    fireEvent.click(await screen.findByRole("button", { name: "Add a check" }));
    const form = screen.getByRole("group", { name: "Add a check" });
    fireEvent.change(await within(form).findByRole("combobox", { name: "Column" }), { target: { value: "amount" } });
    fireEvent.change(within(form).getByRole("textbox", { name: "Lowest" }), { target: { value: "0" } });
    fireEvent.change(within(form).getByRole("combobox", { name: "Rows that break it" }), { target: { value: "quarantine" } });
    fireEvent.click(within(form).getByRole("button", { name: "Add check" }));
    await waitFor(() => expect(sent(calls).find((c) => c.method === "PATCH")?.body).toEqual({ ops: [{
      op: "add_rule", rule: { kind: "range", column: "amount", params: { min: 0, max: null }, action: "quarantine",
                              scope: "dataset" } }] }));
  });

  it("lists suggested checks with their count and reason, and keeps or dismisses one", async () => {
    const suggestion = { id: "rul_s", kind: "range", column: "units", action: "quarantine", words: "units is at most 50",
                         reason: "Orders are small, so a large count is a typo.", count: 3, error: null, sev: "skews" };
    const calls = mockApi({
      "GET /api/v1/clean-plans/pln_1": { ...PLAN, suggestions: [suggestion] },
      "PATCH /api/v1/clean-plans/pln_1": PLAN,
    });
    renderAt(<CleanPlanPanel dataset={WITH_PLAN} layout="centre" />);
    const group = await screen.findByRole("region", { name: "Suggested checks" });
    expect(group).toHaveTextContent("units is at most 50suggested by Sherlock3 rows break it.Orders are small");
    fireEvent.click(within(group).getByRole("button", { name: "Keep" }));
    await waitFor(() => expect(sent(calls).find((c) => c.method === "PATCH")?.body)
      .toEqual({ ops: [{ op: "keep_suggestion", rule_id: "rul_s" }] }));
  });

  it("edits a suggested check's values before keeping it", async () => {
    const suggestion = { id: "rul_s", kind: "range", column: "units", params: { min: null, max: 50 }, action: "quarantine",
                         words: "units is at most 50", count: 3, error: null, sev: "skews" };
    const calls = mockApi({
      "GET /api/v1/clean-plans/pln_1": { ...PLAN, suggestions: [suggestion] },
      "PATCH /api/v1/rules/rul_s": { ...suggestion, params: { min: null, max: 40 } },
    });
    renderAt(<CleanPlanPanel dataset={WITH_PLAN} layout="centre" />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit units is at most 50" }));
    const form = screen.getByRole("group", { name: "Edit units is at most 50" });
    expect(within(form).getByRole("textbox", { name: "Highest" })).toHaveValue("50");
    fireEvent.change(within(form).getByRole("textbox", { name: "Highest" }), { target: { value: "40" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(sent(calls).find((c) => c.method === "PATCH")?.body)
      .toEqual({ params: { min: null, max: 40 }, action: "quarantine" }));
  });

  it("groups the fixes by level, with the review's reason or the default level, while it reviews", async () => {
    const bigFare = PLAN.items.map((i) => (i.id === "pit_fare" ? { ...i, severity: 0.5 } : i));
    mockApi({ "GET /api/v1/clean-plans/pln_1": { ...PLAN, review: "running", items: bigFare } });
    renderAt(<CleanPlanPanel dataset={WITH_PLAN} layout="centre" />);
    expect(await screen.findByText("Reviewing…")).toBeInTheDocument();
    const headings = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(headings).toEqual(["Breaks answers", "Worth a look", "Marked, not changed"]);
    expect(screen.getByText("Averages of the measure can't be read.")).toBeInTheDocument();
    expect(screen.getAllByText("(default level)")).toHaveLength(3); // the three fixes still on code's level
    // Within a level, the biggest first.
    const look = screen.getByRole("region", { name: "Worth a look" });
    expect(within(look).getAllByRole("checkbox").slice(1).map((b) => b.getAttribute("aria-label")))
      .toEqual(["fare: outliers", "age: missing values", "age: outliers"]);
  });

  it("can't start with nothing ticked, and starts the plan's job", async () => {
    const none = { ...PLAN, items: PLAN.items.map((i) => ({ ...i, ticked: false })) };
    mockApi({ "GET /api/v1/clean-plans/pln_1": none });
    const { unmount } = renderAt(<CleanPlanPanel dataset={WITH_PLAN} layout="centre" />);
    expect(await screen.findByRole("button", { name: "Start cleaning (0)" })).toBeDisabled();
    unmount();
    const calls = mockApi({
      "GET /api/v1/clean-plans/pln_1": PLAN,
      "POST /api/v1/datasets/ds_1/clean": { id: "job_1", kind: "clean", status: "queued" },
    });
    renderAt(<CleanPlanPanel dataset={WITH_PLAN} layout="centre" />);
    fireEvent.click(await screen.findByRole("button", { name: "Start cleaning (4)" }));
    await waitFor(() => expect(sent(calls).some((c) => c.path.endsWith("/clean"))).toBe(true));
    expect(sent(calls).find((c) => c.path.endsWith("/clean"))?.body).toEqual({
      mode: "auto", scope: { kind: "all" }, include_user_edited: false, plan_id: "pln_1" });
  });

  it("says why it opened when the After upload setting opened it", async () => {
    mockApi({ "GET /api/v1/clean-plans/pln_1": { ...PLAN, source: "after_upload" } });
    renderAt(<CleanPlanPanel dataset={WITH_PLAN} layout="centre" />);
    expect(await screen.findByText(/Opened because After upload is “Open the cleaning plan”/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change" })).toBeInTheDocument();
  });

  it("takes a ready dataset's right panel while a draft is open, and gives it back", async () => {
    mockApi({
      "GET /api/v1/datasets/ds_1": { ...DS, status: "ready", clean_plan_id: "pln_1" },
      "GET /api/v1/clean-plans/pln_1": PLAN,
    });
    const { unmount } = renderAt(<CsvSidePanel datasetId="ds_1" />);
    expect(await screen.findByRole("heading", { name: "Cleaning plan · v2" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Scope" })).toBeInTheDocument(); // the side layout has the scope
    unmount();
    mockApi({
      "GET /api/v1/datasets/ds_1": { ...DS, status: "ready", clean_plan_id: null },
      "GET /api/v1/datasets/ds_1/steps": [],
      "GET /api/v1/jobs": [],
    });
    renderAt(<CsvSidePanel datasetId="ds_1" />);
    expect(await screen.findByRole("heading", { name: "Changes" })).toBeInTheDocument();
  });

  it("keeps Changes while the offer's plan fills the centre, so the plan shows once", async () => {
    mockApi({
      "GET /api/v1/datasets/ds_1": { ...DS, status: "offer", clean_plan_id: "pln_1" },
      "GET /api/v1/clean-plans/pln_1": PLAN,
      "GET /api/v1/datasets/ds_1/steps": [],
      "GET /api/v1/jobs": [],
    });
    renderAt(<CsvSidePanel datasetId="ds_1" />);
    expect(await screen.findByRole("heading", { name: "Changes" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Cleaning plan · v2" })).toBeNull();
  });
});

describe("cleans opened for some rows go through the plan (PRD CLEAN-1)", () => {
  const NEW_ROWS: CleanPlan = { ...PLAN, scope: { kind: "new_rows", selection_id: null, row_ids: [121, 122], rows: 2 } };
  const CHOSEN: CleanPlan = { ...PLAN, scope: { kind: "selection", selection_id: "sel_9", row_ids: null, rows: 3 } };

  it("the new-rows toast's Clean them opens the plan for those rows and cleans nothing", async () => {
    useEdits.setState({ buffers: { ds_1: { base: 2, edits: {}, newRows: [{ temp_id: "n1", cells: { age: "3" } }, { temp_id: "n2", cells: { age: "4" } }], deleted: [], restored: [] } } });
    const calls = mockApi({
      "POST /api/v1/datasets/ds_1/edits": { step: { id: "stp_3", no: 3 }, version: 3, new_row_ids: { n1: 121, n2: 122 } },
      "POST /api/v1/datasets/ds_1/clean/plan": NEW_ROWS,
    });
    renderAt(<><SaveActions dataset={{ ...DS, status: "ready" }} /><Toaster /></>);
    fireEvent.click(screen.getByRole("button", { name: "Save changes (2)" }));
    fireEvent.click(await screen.findByRole("button", { name: "Clean them" }));
    await waitFor(() => expect(sent(calls).some((c) => c.path.endsWith("/clean/plan"))).toBe(true));
    expect(sent(calls).find((c) => c.path.endsWith("/clean/plan"))?.body).toEqual({ scope: { kind: "new_rows", row_ids: [121, 122] } });
    expect(sent(calls).some((c) => c.path.endsWith("/clean"))).toBe(false);
    expect(useUi.getState().rightOpen).toBe(true);
  });

  it("approving chat's clean opens the plan, not a job", async () => {
    const calls = mockApi({ "POST /api/v1/proposals/prp_1/approve": CHOSEN });
    const proposal = { id: "prp_1", kind: "clean_selection", base_version: 2, status: "pending", summary: "Clean with AI on the 3 selected rows",
                       scope: { kind: "selection", selection_id: "sel_9" }, impact: { cells_changed: 0, rows_affected: 3 } } as const;
    renderAt(<><ProposalView proposal={proposal} dataset={{ ...DS, status: "ready" }} /><Toaster /></>);
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(await screen.findByText("The cleaning plan is open for those rows. Look it over, then press Start cleaning.")).toBeInTheDocument();
    expect(sent(calls).some((c) => c.path.endsWith("/clean"))).toBe(false);
  });

  it("starts on the plan's rows in the side panel, and Start sends them", async () => {
    const calls = mockApi({
      "GET /api/v1/datasets/ds_1": { ...DS, status: "ready", clean_plan_id: "pln_1" },
      "GET /api/v1/clean-plans/pln_1": NEW_ROWS,
      "POST /api/v1/datasets/ds_1/clean": { id: "job_1", kind: "clean", status: "queued" },
    });
    renderAt(<CsvSidePanel datasetId="ds_1" />);
    expect(await screen.findByRole("radio", { name: "The 2 rows you just added" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Whole dataset" })).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Start cleaning (4)" }));
    await waitFor(() => expect(sent(calls).some((c) => c.path.endsWith("/clean"))).toBe(true));
    expect(sent(calls).find((c) => c.path.endsWith("/clean"))?.body.scope).toEqual({ kind: "new_rows", row_ids: [121, 122] });
  });

  it("says which rows in the centre, and Start sends the chat's selection", async () => {
    const calls = mockApi({
      "GET /api/v1/clean-plans/pln_1": CHOSEN,
      "POST /api/v1/datasets/ds_1/clean": { id: "job_1", kind: "clean", status: "queued" },
    });
    renderAt(<CleanPlanPanel dataset={WITH_PLAN} layout="centre" />);
    expect(await screen.findByText("Only the 3 rows you asked to clean.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Start cleaning (4)" }));
    await waitFor(() => expect(sent(calls).some((c) => c.path.endsWith("/clean"))).toBe(true));
    expect(sent(calls).find((c) => c.path.endsWith("/clean"))?.body.scope).toEqual({ kind: "selection", selection_id: "sel_9" });
  });
});

describe("editing the cleaning plan (PRD CLEAN-8b)", () => {
  const patched = (calls: ReturnType<typeof mockApi>) => sent(calls).filter((c) => c.method === "PATCH").map((c) => c.body);

  it("rewrites a fix in plain words, and Reset puts Sherlock's wording back", async () => {
    const edited = { ...PLAN, items: PLAN.items.map((i) => (i.id === "pit_age" ? { ...i, instruction: "Median age by class" } : i)) };
    let current: CleanPlan = PLAN;
    const calls = mockApi({
      "GET /api/v1/clean-plans/pln_1": () => current,
      "PATCH /api/v1/clean-plans/pln_1": (_: URL, init?: RequestInit) => {
        const op = JSON.parse(String(init?.body)).ops[0];
        current = op.instruction ? edited : PLAN;
        return current;
      },
    });
    renderAt(<CleanPlanPanel dataset={WITH_PLAN} layout="centre" />);
    fireEvent.click(await screen.findByRole("button", { name: "Rewrite the fix for age: missing values" }));
    const box = screen.getByRole("textbox", { name: "The fix, in plain words" });
    expect(box).toHaveValue("Fill from a rule over related columns");
    fireEvent.change(box, { target: { value: "Median age by class" } });
    expect(screen.getByRole("button", { name: "Start cleaning (4)" })).toBeDisabled(); // an unsaved edit
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText("edited")).toBeInTheDocument();
    expect(screen.getByText("Median age by class")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start cleaning (4)" })).toBeEnabled();
    expect(patched(calls)[0]).toEqual({ ops: [{ op: "set_instruction", item_id: "pit_age", instruction: "Median age by class" }] });

    fireEvent.click(screen.getByRole("button", { name: "Rewrite the fix for age: missing values" }));
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    await waitFor(() => expect(screen.queryByText("edited")).toBeNull());
    expect(patched(calls)[1]).toEqual({ ops: [{ op: "set_instruction", item_id: "pit_age", instruction: null }] });
  });

  it("adds a step of the user's own, under Your steps, and × removes it", async () => {
    const step = item({ id: "pit_mine", source: "you", key: null, detector: "user_request", column: "region", count: null,
                        severity: null, action: "Trim spaces", instruction: "Trim spaces", module: "yours" });
    let current: CleanPlan = PLAN;
    const calls = mockApi({
      "GET /api/v1/clean-plans/pln_1": () => current,
      "GET /api/v1/datasets/ds_1/datacard": { version: 2, row_count: 120, column_count: 2, quarantined: 0, issues: [],
        target_candidates: [], leakage_candidates: [],
        columns: [{ name: "region", type: "text", role: "dimension", missing: 0, missing_pct: 0, distinct: 6 },
                  { name: "amount", type: "text", role: "dimension", missing: 0, missing_pct: 0, distinct: 9 }] },
      "PATCH /api/v1/clean-plans/pln_1": (_: URL, init?: RequestInit) => {
        const op = JSON.parse(String(init?.body)).ops[0];
        current = op.op === "add" ? { ...PLAN, items: [step, ...PLAN.items] } : PLAN;
        return current;
      },
    });
    renderAt(<CleanPlanPanel dataset={WITH_PLAN} layout="centre" />);
    fireEvent.click(await screen.findByRole("button", { name: "Add a step" }));
    const form = screen.getByRole("group", { name: "Add a step" });
    await waitFor(() => expect(within(form).getByRole("option", { name: "region" })).toBeInTheDocument());
    fireEvent.change(within(form).getByRole("combobox", { name: "Column" }), { target: { value: "region" } });
    fireEvent.change(within(form).getByRole("textbox", { name: "What to do" }), { target: { value: "Trim spaces" } });
    fireEvent.click(within(form).getByRole("button", { name: "Add" }));
    expect(await screen.findByRole("heading", { name: "Your steps" })).toBeInTheDocument();
    expect(patched(calls)[0]).toEqual({ ops: [{ op: "add", column: "region", instruction: "Trim spaces" }] });
    expect(screen.getByRole("checkbox", { name: "region: your step" })).toBeChecked();
    expect(screen.getByRole("button", { name: "Start cleaning (5)" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Remove your step on region" }));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Your steps" })).toBeNull());
    expect(patched(calls)[1]).toEqual({ ops: [{ op: "remove", item_id: "pit_mine" }] });
  });

  it("tells the chat bar which plan is open", async () => {
    mockApi({ "GET /api/v1/clean-plans/pln_1": PLAN });
    const { unmount } = renderAt(<CleanPlanPanel dataset={WITH_PLAN} layout="side" />);
    await screen.findByRole("heading", { name: "Cleaning plan · v2" });
    expect(useUi.getState().planId).toBe("pln_1");
    unmount();
    expect(useUi.getState().planId).toBeNull();
  });
});
