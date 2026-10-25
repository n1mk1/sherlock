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
        notes: ["There are no story cards yet, so this notebook has the widgets only."],
        counts: { steps: 2, widgets: 6, runs: 0, cards: 0 },
        options: { include_data: true, include_cards: true, include_notes: false, include_runs: true, order: "steps_dashboard" },
      },
    });
    useUi.setState({ exportOpen: true });
    renderAt(<ExportDialog dataset={DATASET} />);
    expect(await screen.findByText(/no story cards yet/)).toBeInTheDocument();
  });

  it("asks the preview again when an option changes, without sending unset options", async () => {
    const asked: string[] = [];
    mockApi({
      "GET /api/v1/datasets/ds_1/exports/notebook/preview": (url: URL) => {
        asked.push(url.search);
        const cards = url.searchParams.get("include_cards") === "false" ? 0 : 10;
        return {
          version: 4, notes: [], counts: { steps: 2, widgets: 6, runs: 0, cards },
          options: { include_data: true, include_cards: true, include_notes: false, include_runs: true,
                     order: "steps_dashboard", up_to_step: null },
        };
      },
    });
    useUi.setState({ exportOpen: true });
    renderAt(<ExportDialog dataset={DATASET} />);
    await waitFor(() => expect(document.body.textContent).toContain("10 story cards"));
    fireEvent.click(screen.getByLabelText(/Include story cards/));
    await waitFor(() => expect(asked.some((q) => q.includes("include_cards=false"))).toBe(true));
    expect(asked.every((q) => !q.includes("null"))).toBe(true);
    await waitFor(() => expect(document.body.textContent).toContain("0 story cards"));
  });
});
