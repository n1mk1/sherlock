import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Job, Widget } from "@/api/types";
import { initials } from "@/components/library/LibraryPanel";
import { visibleJobs } from "@/components/shell/JobTray";
import { formatCell, formatNumber, isPctColumn } from "@/lib/format";
import { useFilters } from "@/state/filters";
import { mockApi, renderAt } from "@/test/render";
import { templateSpec } from "./AddWidgetDrawer";
import { derive } from "./Dashboard";
import { compatibleViews, WidgetShell } from "./WidgetShell";

afterEach(() => vi.unstubAllGlobals());

const KPI: Widget = {
  id: "wdg_1", dataset_id: "ds_1", title: "Survival rate", status: "ready", error: null, created_by: "builder",
  version_built: 2, score: 0.2, point: null, deleted_at: null,
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

  it("shows the error with Retry and Show query", async () => {
    mockApi({});
    const explain = vi.fn();
    renderAt(<WidgetShell widget={KPI} version={2} columns={[]} collapsed={false} onToggleCollapse={() => {}} onExplain={explain} />);
    expect(await screen.findByText(/no mock for GET/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show query" }));
    await waitFor(() => expect(explain).toHaveBeenCalled());
  });
});
