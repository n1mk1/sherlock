// UI state (TRD §2 `state/`): panels, the file waiting in the import preview, live job progress.
import { create } from "zustand";
import type { JobProgressEvent } from "@/api/types";

interface UiState {
  leftOpen: boolean;   // on narrow screens the side panels are slide-overs (UI brief §3.1)
  rightOpen: boolean;
  importFile: File | null;
  progress: Record<string, JobProgressEvent>; // dataset_id → latest job.progress
  setLeftOpen: (open: boolean) => void;
  setRightOpen: (open: boolean) => void;
  openImport: (file: File | null) => void;
  setProgress: (e: JobProgressEvent) => void;
}

export const useUi = create<UiState>((set) => ({
  leftOpen: false,
  rightOpen: false,
  importFile: null,
  progress: {},
  setLeftOpen: (leftOpen) => set({ leftOpen }),
  setRightOpen: (rightOpen) => set({ rightOpen }),
  openImport: (importFile) => set({ importFile }),
  setProgress: (e) => set((s) => ({ progress: { ...s.progress, [e.dataset_id]: e } })),
}));
