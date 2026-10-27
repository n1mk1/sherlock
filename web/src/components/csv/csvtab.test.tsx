import { fireEvent, screen, waitFor } from "@testing-library/react";
import { forwardRef, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Dataset } from "@/api/types";
import { mockApi, renderAt } from "@/test/render";
import { CsvTab } from "./CsvTab";

// The real grid draws on a canvas, which jsdom lacks; this one shows whether it was made read-only.
vi.mock("./Grid", () => ({
  Grid: forwardRef<unknown, { readOnly?: boolean }>(function Grid({ readOnly }, _ref) {
    return <div data-testid="grid" data-readonly={String(!!readOnly)} />;
  }),
}));

afterEach(() => vi.unstubAllGlobals());

const DS = {
  id: "ds_1", name: "messy.csv", status: "ready", current_version: 2, row_count: 120, column_count: 4,
  created_at: "", last_opened_at: null, last_tab: null, error: null, clean_plan_id: null,
} as Dataset;

describe("the CSV tab while a job owns the data", () => {
  it.each([
    ["building", "Building your dashboard · editing opens when it finishes"],
    ["cleaning", "Cleaning in progress · editing resumes when it finishes"],
  ] as const)("is read-only with a banner while %s", (status, banner) => {
    mockApi({});
    renderAt(<CsvTab dataset={{ ...DS, status }} />);
    expect(screen.getByRole("status")).toHaveTextContent(banner);
    expect(screen.getByTestId("grid")).toHaveAttribute("data-readonly", "true");
    expect(screen.getByRole("button", { name: /Add row/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Clean with AI/ })).toBeDisabled();
  });

  it("is editable once it's ready", () => {
    mockApi({});
    renderAt(<CsvTab dataset={DS} />);
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getByTestId("grid")).toHaveAttribute("data-readonly", "false");
    expect(screen.getByRole("button", { name: /Add row/ })).toBeEnabled();
  });
});

describe("Find on a new version", () => {
  it("runs again, so its rows and count are the new version's", async () => {
    let finds = 0;
    mockApi({
      "GET /api/v1/datasets/ds_1/find": () => {
        finds += 1;
        return finds === 1
          ? { count: 3, first_matches: [{ row_id: 1, column: "name" }, { row_id: 1, column: "city" }, { row_id: 4, column: "name" }] }
          : { count: 1, first_matches: [{ row_id: 4, column: "name" }] };
      },
      "POST /api/v1/datasets/ds_1/selections": { selection_id: "sel_1", row_count: 2 },
    });
    function Host() { // the dataset page passes the dataset; a new version comes with a new prop
      const [version, setVersion] = useState(2);
      return <><button type="button" onClick={() => setVersion(3)}>v3 arrives</button><CsvTab dataset={{ ...DS, current_version: version }} /></>;
    }
    renderAt(<Host />);
    fireEvent.click(screen.getByRole("button", { name: /^Find$/ }));
    fireEvent.change(screen.getByLabelText("Find"), { target: { value: "smith" } });
    fireEvent.submit(screen.getByLabelText("Find").closest("form")!);
    expect(await screen.findByText(/3 matches in 2 rows/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "v3 arrives" }));
    expect(await screen.findByText(/1 match in 1 row/)).toBeInTheDocument();
    await waitFor(() => expect(finds).toBe(2));
  });
});
