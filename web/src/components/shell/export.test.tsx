import { screen } from "@testing-library/react";
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
});
