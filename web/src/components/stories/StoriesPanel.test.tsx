import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Card } from "@/api/types";
import { mockApi, renderAt } from "@/test/render";
import { StoriesPanel } from "./StoriesPanel";
import { StoryCard } from "./StoryCard";

afterEach(() => vi.unstubAllGlobals());

describe("off a dataset route (Day 9 review)", () => {
  it("the stories panel asks the API for nothing", async () => {
    const fetchMock = mockApi({});
    renderAt(<StoriesPanel />, "/");
    expect(await screen.findByText("Stories appear once the dashboard is built.")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled(); // it used to GET /api/v1/datasets//widgets, a 404
  });
});


describe("user-written text once the data moves on (plan 2b.7)", () => {
  const typed: Card = {
    id: "crd_1", dataset_id: "ds_1", kind: "widget", widget_id: "wdg_1", source_card_ids: null, fact_sheet_id: "fs_1",
    status: "ready", edited_by_user: true, changed_badge: false, suggestion: null, version: 5, narrated_by: null,
    updated_at: "", facts: {}, related: [],
    headline: { blocks: [{ type: "paragraph", runs: [{ type: "text", text: "Most orders ship late" }] }] },
    body: { blocks: [{ type: "paragraph", runs: [{ type: "text", text: "About " },
      { type: "chip", id: "u1", key: null, value: "zero", unverified: true }, { type: "text", text: " arrive early." }] }] },
  };

  function renderCard(card: Card, currentVersion: number) {
    mockApi({});
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(["datasets", "ds_1"], { id: "ds_1", current_version: currentVersion });
    return render(
      <QueryClientProvider client={qc}>
        <MemoryRouter><StoryCard card={card} title="Orders by region" onEvidence={() => {}} /></MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it("says which version an edited card's words describe, and asks to check typed numbers", () => {
    renderCard(typed, 7);
    expect(screen.getByText("Written on v5, data is now v7")).toBeInTheDocument();
    expect(screen.getByText("Has numbers you typed; check them")).toBeInTheDocument();
  });

  it("says nothing while the data is the version the words were written on", () => {
    renderCard(typed, 5);
    expect(screen.queryByText(/Written on v/)).toBeNull();
    expect(screen.queryByText(/Has numbers you typed/)).toBeNull();
  });

  it("names only the typed numbers on a card Sherlock wrote but the user never edited", () => {
    renderCard({ ...typed, edited_by_user: false }, 7);
    expect(screen.queryByText(/Written on v/)).toBeNull();
    expect(screen.getByText("Has numbers you typed; check them")).toBeInTheDocument();
  });
});
