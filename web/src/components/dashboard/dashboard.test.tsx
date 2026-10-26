import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Job, Widget } from "@/api/types";
import { initials } from "@/components/library/LibraryPanel";
import { JobTray, visibleJobs } from "@/components/shell/JobTray";
import { formatCell, formatNumber, isPctColumn } from "@/lib/format";
import { useLocation } from "react-router-dom";
import { appliedFilter, useFilters } from "@/state/filters";
import { useUi } from "@/state/ui";
import { useDatasetEvents, useWidgets } from "@/api/queries";
import { stubEventSource } from "@/test/eventsource";
import { mockApi, renderAt } from "@/test/render";
import { templateSpec } from "./AddWidgetDrawer";
import { derive, toStored, useWidgetParam } from "./Dashboard";
import { compatibleViews, WidgetShell } from "./WidgetShell";

afterEach(() => vi.unstubAllGlobals());

const KPI: Widget = {
  id: "wdg_1", dataset_id: "ds_1", title: "Survival rate", status: "ready", error: null, created_by: "builder",
  version_built: 2, score: 0.2, point: null, updated_at: "2026-10-26T00:00:00Z", deleted_at: null,
  spec: {
    scope: { columns: { x: null, y: "survived" }, rows: { inherit_global_filters: true } },
    op: { type: "sql", sql: "SELECT AVG(survived) AS rate, COUNT(*) AS n FROM t WHERE {{rows}}" },
    view: { type: "kpi", options: { value: "rate", format: "pct", sub: "n" } },
  },
};

describe("formatting", () => {
  it("formats like the server's chips", () => {
    expect(formatNumber(0.7274, true)).toBe("72.7%");
    expect(formatNumber(1025982.16)).toBe("1,025,982");
    expect(formatNumber(87.509)).toBe("87.51");
    expect(formatNumber(1309)).toBe("1,309");
    expect(formatCell(null)).toBe("—");
    expect(isPctColumn("survival_rate", [0.2, 0.7])).toBe(true);
    expect(isPctColumn("survival_rate", [12])).toBe(false);
    expect(isPctColumn("fare", [0.5])).toBe(false);
  });
});

describe("dashboard helpers", () => {
  it("derives a small layout from lg in reading order", () => {
    const lg = [
      { i: "k1", x: 0, y: 0, w: 3, h: 3 }, { i: "k2", x: 3, y: 0, w: 3, h: 3 },
      { i: "b", x: 6, y: 3, w: 6, h: 7 }, { i: "a", x: 0, y: 3, w: 6, h: 7 },
    ];
    const sm = derive(lg, 4);
    expect(sm.map((i) => [i.i, i.x, i.y, i.w])).toEqual([["k1", 0, 0, 2], ["k2", 2, 0, 2], ["a", 0, 3, 4], ["b", 0, 10, 4]]);
  });

  it("keeps a collapsed widget's height when it collapses and when it expands", () => {
    const stored = { lg: [{ i: "a", x: 0, y: 0, w: 6, h: 7 }, { i: "b", x: 6, y: 0, w: 6, h: 7 }] };
    const drawnCollapsed = { lg: [{ i: "a", x: 0, y: 0, w: 6, h: 1 }, { i: "b", x: 6, y: 0, w: 6, h: 7 }] };
    const collapsing = toStored({ lg: stored.lg }, stored, new Set(), new Set(["a"]));
    expect(collapsing.lg[0]).toEqual({ i: "a", x: 0, y: 0, w: 6, h: 7, collapsed: true });
    const collapsedStored = { lg: [{ ...stored.lg[0], collapsed: true }, stored.lg[1]] };
    const expanding = toStored(drawnCollapsed, collapsedStored, new Set(["a"]), new Set());
    expect(expanding.lg.map((i) => [i.i, i.h, i.collapsed])).toEqual([["a", 7, undefined], ["b", 7, undefined]]);
  });

  it("lists the views that can draw a result", () => {
    const data = (columns: string[], rows: unknown[][]) => ({
      version: 2, columns: columns.map((c) => ({ name: c, type: c === "period" ? "DATE" : "BIGINT" })), rows,
      row_count: rows.length, truncated: false,
    });
    expect(compatibleViews(data(["n"], [[5]]))).toEqual(["kpi", "table"]);
    expect(compatibleViews(data(["pclass", "rate"], [[1, 0.6], [2, 0.4]]))).toEqual(["bar", "pie", "ring", "table"]);
    expect(compatibleViews(data(["period", "n"], [["2024-01-01", 3], ["2024-02-01", 4]]))[0]).toBe("line");
  });

  it("builds template widgets with {{rows}}", () => {
    const bar = templateSpec("bar", "pclass", "fare", []);
    expect(bar.title).toBe("Average fare by pclass");
    expect(bar.spec.op.type === "sql" && bar.spec.op.sql).toContain("WHERE {{rows}}");
    expect(templateSpec("kpi", "", "", []).title).toBe("Rows");
  });

  it("keeps running, recent and failed jobs in the tray", () => {
    const now = Date.parse("2026-10-25T00:10:00Z");
    const job = (id: string, status: Job["status"], finished: string | null) =>
      ({ id, status, finished_at: finished, kind: "clean", progress: { step: 0, of: 0, label: "", pct: 0 } }) as Job;
    const jobs = [job("a", "running", null), job("b", "done", "2026-10-25T00:09:30Z"), job("c", "done", "2026-10-25T00:01:00Z"),
      job("d", "failed", "2026-10-25T00:00:00Z"), job("e", "failed", "2026-10-25T00:00:00Z")];
    expect(visibleJobs(jobs, new Set(["e"]), now).map((j) => j.id)).toEqual(["a", "b", "d"]);
    expect(initials("titanic3.csv (sample)")).toBe("TI");
    expect(initials("sales_semicolon.csv")).toBe("SS");
  });
});

describe("job tray", () => {
  it("is a popover whose Retry and Dismiss are reached with Tab", async () => {
    mockApi({
      "GET /api/v1/jobs": [{ id: "job_1", dataset_id: "ds_1", kind: "clean", status: "failed", error: "Model unavailable",
        progress: { step: 0, of: 0, label: "", pct: 0 }, created_at: "", started_at: null, finished_at: null, result: null }],
      "GET /api/v1/datasets": [],
    });
    renderAt(<JobTray />);
    fireEvent.click(await screen.findByRole("button", { name: /Background jobs/ }));
    const retry = await screen.findByRole("button", { name: "Retry" });
    expect(screen.getByRole("dialog")).toContainElement(retry);
    // A dropdown menu cancels Tab inside it (UI/UX brief §8: every control is reachable by keyboard).
    expect(fireEvent.keyDown(retry, { key: "Tab" })).toBe(true);
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeInTheDocument();
  });
});

describe("widget shell", () => {
  it("loads its data with the global filter and shows the KPI", async () => {
    const fetchMock = mockApi({
      "GET /api/v1/widgets/wdg_1/data": (url: URL) => ({
        version: 2, columns: [{ name: "rate", type: "DOUBLE" }, { name: "n", type: "BIGINT" }],
        rows: url.searchParams.get("filters") ? [[0.727, 466]] : [[0.382, 1309]], row_count: 1, truncated: false,
      }),
    });
    renderAt(<WidgetShell widget={KPI} version={2} columns={["sex", "survived"]} collapsed={false} onToggleCollapse={() => {}} onExplain={() => {}} />);
    expect(await screen.findByText("38.2%")).toBeInTheDocument();
    expect(screen.getByText("of 1,309 rows")).toBeInTheDocument();
    useFilters.getState().toggle("ds_1", { col: "sex", op: "eq", value: "female" });
    expect(await screen.findByText("72.7%")).toBeInTheDocument();
    const filtered = fetchMock.mock.calls.map(([u]) => String((u as Request).url ?? u)).find((u) => u.includes("filters="));
    expect(decodeURIComponent(filtered!)).toContain('{"and":[{"col":"sex","op":"eq","value":"female"}]}');
    useFilters.getState().clear("ds_1");
  });

  it("reads its data again when widget.updated brings a new updated_at (a changed spec)", async () => {
    // Plan 1.5 (A20): chat's "make it a pie chart" changed the spec, but the data key didn't move, so the
    // chart kept the old query's rows.
    const ES = stubEventSource();
    let current = KPI;
    let reads = 0;
    mockApi({
      "GET /api/v1/datasets/ds_1/widgets": () => ({ widgets: [current], layout: { lg: [] } }),
      "GET /api/v1/widgets/wdg_1/data": () => {
        reads += 1;
        return { version: 2, columns: [{ name: "rate", type: "DOUBLE" }, { name: "n", type: "BIGINT" }],
          rows: [[current === KPI ? 0.382 : 0.5, 1309]], row_count: 1, truncated: false };
      },
    });
    function Live() {
      useDatasetEvents("ds_1", () => {});
      const w = useWidgets("ds_1").data?.widgets[0];
      return w ? <WidgetShell widget={w} version={2} columns={[]} collapsed={false} onToggleCollapse={() => {}} onExplain={() => {}} /> : null;
    }
    renderAt(<Live />);
    expect(await screen.findByText("38.2%")).toBeInTheDocument();
    current = { ...KPI, updated_at: "2026-10-26T00:01:00Z",
      spec: { ...KPI.spec, op: { type: "sql", sql: "SELECT AVG(survived) AS rate, COUNT(*) AS n FROM t WHERE {{rows}} AND sex = 'female'" } } };
    act(() => ES.last().emit("widget.updated", current, 7));
    expect(await screen.findByText("50.0%")).toBeInTheDocument();
    expect(reads).toBe(2); // the old key isn't read again on the way
    // A write that keeps updated_at (nothing in the key moved) reads the data again too.
    act(() => ES.last().emit("widget.updated", current, 8));
    await waitFor(() => expect(reads).toBe(3));
  });

  it("shows the error with Retry and Show query", async () => {
    mockApi({});
    const explain = vi.fn();
    renderAt(<WidgetShell widget={KPI} version={2} columns={[]} collapsed={false} onToggleCollapse={() => {}} onExplain={explain} />);
    expect(await screen.findByText(/no mock for GET/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show query" }));
    await waitFor(() => expect(explain).toHaveBeenCalled());
  });
});

describe("review fixes", () => {
  const BAR: Widget = { ...KPI, id: "wdg_2", spec: { ...KPI.spec, scope: { ...KPI.spec.scope, columns: { x: "sex", y: "rate" } } } };

  it("shows in How do you know? the filter the widget applies", () => {
    // Review F3: a chart doesn't filter itself by its own category, but the drawer added the filter anyway.
    const onSex = { col: "sex", op: "eq", value: "female" } as const;
    expect(appliedFilter(BAR, onSex)).toBeNull();
    expect(appliedFilter(KPI, onSex)).toEqual(onSex);
    const optedOut = { ...KPI, spec: { ...KPI.spec, scope: { ...KPI.spec.scope, rows: { inherit_global_filters: false } } } };
    expect(appliedFilter(optedOut, onSex)).toBeNull();
    expect(appliedFilter(KPI, null)).toBeNull();
  });

  it("flashes the widget named by ?widget= and drops the parameter", async () => {
    // Review F12: chat's "Open the widget" linked to ?widget=:id, which nothing read.
    let search = "";
    function Probe({ widgets }: { widgets?: Widget[] }) {
      useWidgetParam(widgets);
      search = useLocation().search;
      return null;
    }
    useUi.setState({ flashWidget: null });
    renderAt(<Probe widgets={[KPI, BAR]} />, "/d/ds_1/dashboard?widget=wdg_2");
    await waitFor(() => expect(useUi.getState().flashWidget).toBe("wdg_2"));
    await waitFor(() => expect(search).toBe(""));
  });
});
