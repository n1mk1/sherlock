// Flow tab state shared outside the canvas: the selected cards (the chat's context, App Flow §12.2),
// the node counts the header shows, connect mode, and the canvas's commands for the header buttons.
import { create } from "zustand";

/** The drag payload type of a palette row (a card ID). */
export const CARD_DRAG = "application/x-sherlock-card";

export interface FlowCommands {
  addNote: () => void;
  fitView: () => void;
  placeCard: (cardId: string) => void;
}

interface FlowState {
  selectedCardIds: string[];
  selectedCount: number; // nodes of any kind
  nodeCount: number;
  connecting: boolean;
  commands: FlowCommands | null;
  setSelection: (cardIds: string[], count: number) => void;
  setNodeCount: (n: number) => void;
  setConnecting: (on: boolean) => void;
  setCommands: (c: FlowCommands | null) => void;
}

export const useFlow = create<FlowState>((set) => ({
  selectedCardIds: [],
  selectedCount: 0,
  nodeCount: 0,
  connecting: false,
  commands: null,
  setSelection: (selectedCardIds, selectedCount) => set({ selectedCardIds, selectedCount }),
  setNodeCount: (nodeCount) => set({ nodeCount }),
  setConnecting: (connecting) => set({ connecting }),
  setCommands: (commands) => set({ commands }),
}));
