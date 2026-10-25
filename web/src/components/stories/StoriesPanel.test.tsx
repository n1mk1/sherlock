import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockApi, renderAt } from "@/test/render";
import { StoriesPanel } from "./StoriesPanel";

afterEach(() => vi.unstubAllGlobals());

describe("off a dataset route (Day 9 review)", () => {
  it("the stories panel asks the API for nothing", async () => {
    const fetchMock = mockApi({});
    renderAt(<StoriesPanel />, "/");
    expect(await screen.findByText("Stories appear once the dashboard is built.")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled(); // it used to GET /api/v1/datasets//widgets, a 404
  });
});

