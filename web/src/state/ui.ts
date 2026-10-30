// UI state (TRD §2 `state/`): panels, the file waiting in the import preview, live job progress.
import { create } from "zustand";
import type { Sort } from "@/api/csv";
import type { JobProgressEvent } from "@/api/types";

// Panel sizes and the library rail persist per browser (UI brief §3.1); storage may be unavailable.
const STORE = "sherlock.panels";
interface Panels {
  railed: boolean;
  leftWidth: number;
  rightWidth: number;
}
function loadPanels(): Panels {
  const fallback = { railed: false, leftWidth: 240, rightWidth: 340 };
  try {
    return { ...fallback, ...JSON.parse(localStorage.getItem(STORE) ?? "{}") };
  } catch {
    return fallback;
  }
}
function savePanels(p: Panels) {
  try {
    localStorage.setItem(STORE, JSON.stringify(p));
  } catch {
    /* private mode: sizes just don't persist */
  }
}
export const LEFT = { min: 200, max: 320 };
export const RIGHT = { min: 300, max: 480 };
const clamp = (v: number, r: { min: number; max: number }) => Math.round(Math.min(r.max, Math.max(r.min, v)));

interface UiState extends Panels {
  setRailed: (railed: boolean) => void;
  setPanelWidth: (side: "left" | "right", width: number) => void;
  leftOpen: boolean;   // on narrow screens the side panels are slide-overs (UI brief §3.1)
  rightOpen: boolean;
  importFile: File | null;
  progress: Record<string, JobProgressEvent>; // dataset_id → latest job.progress
  chatOpen: boolean;          // the thread above the chat bar
  exportOpen: boolean;        // the Export notebook dialog (App Flow §17)
  setExportOpen: (open: boolean) => void;
  exportPreset: Record<string, boolean> | null; // options chat asked for ("export a notebook without the data")
  openExport: (preset: Record<string, boolean> | null) => void;
  planId: string | null;      // the cleaning plan on screen: the chat sends it, so it can change the plan
  setPlanId: (id: string | null) => void;
  csvSelection: { row_ids: number[]; columns: string[] } | null; // the CSV grid's selection, the chat's context there
  setCsvSelection: (s: { row_ids: number[]; columns: string[] } | null) => void;
  /** A sort chat asked for ("sort by fare"), for the grid to apply; `n` tells a repeat of the same sort apart. */
  gridSort: { sort: Sort | null; n: number } | null;
  sortGrid: (sort: Sort | null) => void;
  setChatOpen: (open: boolean) => void;
  setLeftOpen: (open: boolean) => void;
  setRightOpen: (open: boolean) => void;
  openImport: (file: File | null) => void;
  setProgress: (e: JobProgressEvent) => void;
}

export const useUi = create<UiState>((set, get) => ({
  ...loadPanels(),
  setRailed: (railed) => {
    set({ railed });
    const { leftWidth, rightWidth } = get();
    savePanels({ railed, leftWidth, rightWidth });
  },
  setPanelWidth: (side, width) => {
    set(side === "left" ? { leftWidth: clamp(width, LEFT) } : { rightWidth: clamp(width, RIGHT) });
    const { railed, leftWidth, rightWidth } = get();
    savePanels({ railed, leftWidth, rightWidth });
  },
  leftOpen: false,
  rightOpen: false,
  importFile: null,
  progress: {},
  chatOpen: false,
  exportOpen: false,
  setExportOpen: (exportOpen) => set({ exportOpen }),
  exportPreset: null,
  openExport: (exportPreset) => set({ exportPreset, exportOpen: true }),
  planId: null,
  setPlanId: (planId) => set({ planId }),
  csvSelection: null,
  setCsvSelection: (csvSelection) => set({ csvSelection }),
  gridSort: null,
  sortGrid: (sort) => set({ gridSort: { sort, n: (get().gridSort?.n ?? 0) + 1 } }),
  setChatOpen: (chatOpen) => set({ chatOpen }),
  setLeftOpen: (leftOpen) => set({ leftOpen }),
  setRightOpen: (rightOpen) => set({ rightOpen }),
  openImport: (importFile) => set({ importFile }),
  setProgress: (e) => set((s) => ({ progress: { ...s.progress, [e.dataset_id]: e } })),
}));
