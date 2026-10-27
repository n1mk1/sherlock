import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Dataset } from "@/api/types";
import { useUi } from "@/state/ui";
import { mockApi, renderAt } from "@/test/render";
import { ExportDialog } from "./ExportDialog";

afterEach(() => {
  vi.unstubAllGlobals();
  useUi.setState({ exportOpen: false });
});

const DATASET = { id: "ds_1", name: "titanic3.csv", status: "ready", current_version: 4 } as Dataset;

describe("export dialog", () => {
  it("shows the preview's notes (TRD §4.2), not an empty warning box", async () => {
    mockApi({
      "GET /api/v1/datasets/ds_1/exports/notebook/preview": {
        version: 4,
        notes: ["Step 3 runs code the notebook can't replay, so it loads that version's data."],
        counts: { steps: 2, runs: 0 },
        options: { include_data: true, include_runs: true },
      },
    });
    useUi.setState({ exportOpen: true });
    renderAt(<ExportDialog dataset={DATASET} />);
    expect(await screen.findByText(/can't replay/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/story cards|canvas notes/i)).toBeNull();
    expect(screen.queryByRole("radiogroup", { name: "Order" })).toBeNull();
  });

  it("asks the preview again when an option changes, without sending unset options", async () => {
    const asked: string[] = [];
    mockApi({
      "GET /api/v1/datasets/ds_1/exports/notebook/preview": (url: URL) => {
        asked.push(url.search);
        const runs = url.searchParams.get("include_runs") === "false" ? 0 : 3;
        return {
          version: 4, notes: [], counts: { steps: 2, runs },
          options: { include_data: true, include_runs: true, up_to_step: null },
        };
      },
    });
    useUi.setState({ exportOpen: true });
    renderAt(<ExportDialog dataset={DATASET} />);
    await waitFor(() => expect(document.body.textContent).toContain("2 steps and 3 model runs"));
    fireEvent.click(screen.getByLabelText(/Include ML runs/));
    await waitFor(() => expect(asked.some((q) => q.includes("include_runs=false"))).toBe(true));
    expect(asked.every((q) => !q.includes("null"))).toBe(true);
    await waitFor(() => expect(document.body.textContent).toContain("0 model runs"));
  });

  it("opens with Ctrl+Shift+E even when the focused element stops the key (the CSV grid does)", async () => {
    mockApi({
      "GET /api/v1/datasets/ds_1/exports/notebook/preview": {
        version: 4, notes: [], counts: { steps: 2, runs: 0 },
        options: { include_data: true, include_runs: true },
      },
    });
    renderAt(<><div data-testid="grid" tabIndex={0} onKeyDown={(e) => e.stopPropagation()} /><ExportDialog dataset={DATASET} /></>);
    fireEvent.keyDown(screen.getByTestId("grid"), { key: "E", ctrlKey: true, shiftKey: true });
    expect(useUi.getState().exportOpen).toBe(true);
  });
});
