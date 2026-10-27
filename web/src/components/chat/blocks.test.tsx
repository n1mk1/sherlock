import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderAt } from "@/test/render";
import { BlockView } from "./Blocks";

describe("chat answer blocks", () => {
  it("sets general knowledge apart in a chat answer", () => {
    renderAt(<BlockView datasetId="ds_1" block={{ type: "text", labeled: "general", body: { blocks: [{ type: "paragraph", runs: [
      { type: "text", text: "In general (not from your data): " }, { type: "text", text: "Siblings or spouses aboard." }] }] } }} />);
    expect(screen.getByTitle("From the model's general knowledge, not computed from your data").textContent)
      .toContain("Siblings or spouses aboard.");
  });

  it("opens a table answer's rows in the grid", () => {
    renderAt(<BlockView datasetId="ds_1" block={{ type: "table", columns: [{ name: "name", type: "VARCHAR" }],
      rows: [["Allen"]], total: 40, selection_id: "sel_1" }} />);
    expect(screen.getByRole("link", { name: "Open all 40 rows in CSV" })).toHaveAttribute("href", "/d/ds_1?rows=sel_1");
  });
});
