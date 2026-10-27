import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FlowStatus } from "@/components/flow/FlowPalette";
import { useFlow } from "@/state/flow";

const commands = { addNote: vi.fn(), fitView: vi.fn(), placeCard: vi.fn(), removeSelected: vi.fn(), connectSelected: vi.fn(), undo: vi.fn(), redo: vi.fn() };

describe("FlowStatus, the selection's actions (App Flow §12.1)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useFlow.setState({ nodeCount: 6, selectedCount: 0, selectedEdgeCount: 0, selectedCardIds: [], commands });
  });

  it("shows only the count with nothing selected", () => {
    render(<FlowStatus />);
    expect(screen.getByRole("status")).toHaveTextContent("Story canvas · 6 nodes");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("offers Make sense of this, Connect and Remove for two selected cards", () => {
    useFlow.setState({ selectedCount: 2, selectedCardIds: ["crd_1", "crd_2"] });
    render(<FlowStatus />);
    expect(screen.getByRole("status")).toHaveTextContent("Story canvas · 6 nodes · 2 selected");
    expect(screen.getByRole("button", { name: "Make sense of this" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Connect/ }));
    expect(commands.connectSelected).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Remove 2 nodes from the canvas" }));
    expect(commands.removeSelected).toHaveBeenCalled();
  });

  it("names a selected connection and offers Remove alone", () => {
    useFlow.setState({ selectedEdgeCount: 1 });
    render(<FlowStatus />);
    expect(screen.getByRole("status")).toHaveTextContent("· 1 connection selected");
    expect(screen.queryByRole("button", { name: /Connect|Make sense/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Remove 1 connection from the canvas" })).toBeInTheDocument();
  });
});
