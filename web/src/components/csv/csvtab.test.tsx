import { screen } from "@testing-library/react";
import { forwardRef } from "react";
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
