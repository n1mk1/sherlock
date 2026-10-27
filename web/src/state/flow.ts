// Flow tab state shared outside the canvas: the selected cards (the chat's context, App Flow §12.2),
// the counts the status row shows, connect mode, what Undo and Redo would do, and the canvas's
// commands for the header and status-row buttons.
import { create } from "zustand";

/** The drag payload type of a palette row (a card ID). */
export const CARD_DRAG = "application/x-sherlock-card";

export interface FlowCommands {
  addNote: () => void;
  fitView: () => void;
  placeCard: (cardId: string) => void;
  removeSelected: () => void;
  connectSelected: () => void;
  undo: () => void;
  redo: () => void;
}

interface FlowState {
  selectedCardIds: string[];
  selectedCount: number; // nodes of any kind
  selectedEdgeCount: number;
  nodeCount: number;
  connecting: boolean;
  undoLabel: string | null;
  redoLabel: string | null;
  commands: FlowCommands | null;
  setSelection: (cardIds: string[], count: number, edgeCount: number) => void;
  setNodeCount: (n: number) => void;
  setConnecting: (on: boolean) => void;
  setHistory: (undoLabel: string | null, redoLabel: string | null) => void;
  setCommands: (c: FlowCommands | null) => void;
}

export const useFlow = create<FlowState>((set) => ({
  selectedCardIds: [],
  selectedCount: 0,
  selectedEdgeCount: 0,
  nodeCount: 0,
  connecting: false,
  undoLabel: null,
  redoLabel: null,
  commands: null,
  setSelection: (selectedCardIds, selectedCount, selectedEdgeCount) => set({ selectedCardIds, selectedCount, selectedEdgeCount }),
  setNodeCount: (nodeCount) => set({ nodeCount }),
  setConnecting: (connecting) => set({ connecting }),
  setHistory: (undoLabel, redoLabel) => set({ undoLabel, redoLabel }),
  setCommands: (commands) => set({ commands }),
}));
