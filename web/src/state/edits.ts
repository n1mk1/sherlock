// The CSV tab's pending edits (App Flow §8.2, Schema §5): a client-side buffer per dataset, mirrored
// to local storage under `sherlock:edits:<dataset>:<version>`, where the version is the one the
// edits were made on (their base). Save sends it as one EditBatch; Discard clears it. It survives a
// reload (PRD §7.11). Cut 5 removes the buffer's undo/redo, so lines are removed one by one instead.
// Another tab's change to a buffer (an edit, a save, a discard) reaches this one through the
// `storage` event, so two tabs never show, or save, different pending edits.
import { create } from "zustand";

export interface CellEdit {
  row_id: number;
  column: string;
  value: string; // what was typed; "" is a blank cell
  old: unknown;  // the value it replaces, for the Changes panel
}

export interface NewRow {
  temp_id: string;
  cells: Record<string, string>;
}

export interface Buffer {
  base: number; // the version the edits were made on
  edits: Record<string, CellEdit>; // `${row_id}:${column}`
  newRows: NewRow[];
  deleted: number[];
  restored: number[];
}

export const editKey = (rowId: number, column: string) => `${rowId}:${column}`;
const storeKey = (datasetId: string, version: number) => `sherlock:edits:${datasetId}:${version}`;
const empty = (base: number): Buffer => ({ base, edits: {}, newRows: [], deleted: [], restored: [] });

export function pendingCount(b: Buffer | undefined): number {
  if (!b) return 0;
  return Object.keys(b.edits).length + b.newRows.length + b.deleted.length + b.restored.length;
}

/** The buffer for a dataset from local storage: the newest base version that has one. */
function load(datasetId: string): Buffer | undefined {
  try {
    let best: Buffer | undefined;
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (!k?.startsWith(`sherlock:edits:${datasetId}:`)) continue;
      const b = JSON.parse(localStorage.getItem(k) ?? "null") as Buffer | null;
      if (b && pendingCount(b) > 0 && (!best || b.base > best.base)) best = b;
    }
    return best;
  } catch {
    return undefined;
  }
}

function persist(datasetId: string, b: Buffer | undefined, previousBase?: number) {
  try {
    if (previousBase !== undefined && previousBase !== b?.base) localStorage.removeItem(storeKey(datasetId, previousBase));
    if (!b) return;
    if (pendingCount(b) === 0) localStorage.removeItem(storeKey(datasetId, b.base));
    else localStorage.setItem(storeKey(datasetId, b.base), JSON.stringify(b));
  } catch {
    /* private mode: edits just don't survive a reload */
  }
}

let nextTemp = 1;

interface EditsState {
  buffers: Record<string, Buffer>;
  get: (datasetId: string) => Buffer | undefined;
  /** Load the stored buffer for a dataset once (on opening the CSV tab). */
  hydrate: (datasetId: string) => void;
  setCell: (datasetId: string, version: number, edit: CellEdit) => void;
  addRow: (datasetId: string, version: number) => string;
  setNewCell: (datasetId: string, tempId: string, column: string, value: string) => void;
  toggleDelete: (datasetId: string, version: number, rowIds: number[]) => void;
  toggleRestore: (datasetId: string, version: number, rowIds: number[]) => void;
  removeEdit: (datasetId: string, key: string) => void;
  removeNewRow: (datasetId: string, tempId: string) => void;
  rebase: (datasetId: string, version: number, dropKeys: string[]) => void;
  discard: (datasetId: string) => void;
}

export const useEdits = create<EditsState>((set, get) => {
  const update = (datasetId: string, version: number, fn: (b: Buffer) => Buffer) => {
    const prev = get().buffers[datasetId];
    const next = fn(prev ? { ...prev } : empty(version));
    persist(datasetId, next, prev?.base);
    set((s) => ({ buffers: { ...s.buffers, [datasetId]: next } }));
  };
  const existing = (datasetId: string, fn: (b: Buffer) => Buffer) => {
    const b = get().buffers[datasetId];
    if (b) update(datasetId, b.base, fn);
  };
  return {
    buffers: {},
    get: (datasetId) => get().buffers[datasetId],
    hydrate: (datasetId) => {
      if (get().buffers[datasetId]) return;
      const b = load(datasetId);
      if (b) set((s) => ({ buffers: { ...s.buffers, [datasetId]: b } }));
    },
    setCell: (datasetId, version, edit) =>
      update(datasetId, version, (b) => {
        const edits = { ...b.edits };
        const key = editKey(edit.row_id, edit.column);
        const prev = edits[key];
        const old = prev ? prev.old : edit.old;
        // Typing the original value back removes the edit.
        if (String(old ?? "") === edit.value) delete edits[key];
        else edits[key] = { ...edit, old };
        return { ...b, edits };
      }),
    addRow: (datasetId, version) => {
      const temp = `new${Date.now().toString(36)}${nextTemp++}`;
      update(datasetId, version, (b) => ({ ...b, newRows: [{ temp_id: temp, cells: {} }, ...b.newRows] }));
      return temp;
    },
    setNewCell: (datasetId, tempId, column, value) =>
      existing(datasetId, (b) => ({
        ...b,
        newRows: b.newRows.map((r) => (r.temp_id === tempId ? { ...r, cells: { ...r.cells, [column]: value } } : r)),
      })),
    toggleDelete: (datasetId, version, rowIds) =>
      update(datasetId, version, (b) => {
        const set = new Set(b.deleted);
        const allMarked = rowIds.every((r) => set.has(r));
        for (const r of rowIds) (allMarked ? set.delete(r) : set.add(r));
        // A row marked for deletion keeps no cell edits (the server refuses both in one save).
        const edits = Object.fromEntries(Object.entries(b.edits).filter(([, e]) => !set.has(e.row_id)));
        return { ...b, deleted: [...set].sort((x, y) => x - y), edits };
      }),
    toggleRestore: (datasetId, version, rowIds) =>
      update(datasetId, version, (b) => {
        const set = new Set(b.restored);
        const allMarked = rowIds.every((r) => set.has(r));
        for (const r of rowIds) (allMarked ? set.delete(r) : set.add(r));
        return { ...b, restored: [...set].sort((x, y) => x - y) };
      }),
    removeEdit: (datasetId, key) =>
      existing(datasetId, (b) => {
        const edits = { ...b.edits };
        delete edits[key];
        if (key.startsWith("deleted:")) return { ...b, deleted: b.deleted.filter((r) => `deleted:${r}` !== key) };
        if (key.startsWith("restored:")) return { ...b, restored: b.restored.filter((r) => `restored:${r}` !== key) };
        return { ...b, edits };
      }),
    removeNewRow: (datasetId, tempId) => existing(datasetId, (b) => ({ ...b, newRows: b.newRows.filter((r) => r.temp_id !== tempId) })),
    rebase: (datasetId, version, dropKeys) =>
      existing(datasetId, (b) => {
        const edits = { ...b.edits };
        for (const k of dropKeys) delete edits[k];
        return { ...b, base: version, edits };
      }),
    discard: (datasetId) => {
      const prev = get().buffers[datasetId];
      if (prev) persist(datasetId, empty(prev.base), prev.base);
      set((s) => {
        const buffers = { ...s.buffers };
        delete buffers[datasetId];
        return { buffers };
      });
    },
  };
});

const KEY = /^sherlock:edits:(.+):\d+$/;

/** Another tab changed a dataset's stored buffer: this tab takes the stored one (or none). A dataset this
 * tab hasn't opened is left for `hydrate`. */
export function onStorage(e: Pick<StorageEvent, "key">) {
  if (e.key === null) return; // storage cleared: buffers already shown stay until their tab saves
  const datasetId = e.key.match(KEY)?.[1];
  if (!datasetId || !(datasetId in useEdits.getState().buffers)) return;
  const b = load(datasetId);
  useEdits.setState((s) => {
    const buffers = { ...s.buffers };
    if (b) buffers[datasetId] = b;
    else delete buffers[datasetId];
    return { buffers };
  });
}

if (typeof window !== "undefined") window.addEventListener("storage", onStorage);

/** The EditBatch (TRD §4.3) for a buffer. */
export function toBatch(b: Buffer, base = b.base) {
  return {
    base_version: base,
    edits: Object.values(b.edits).map((e) => ({ row_id: e.row_id, column: e.column, value: e.value })),
    new_rows: b.newRows.map((r) => ({ temp_id: r.temp_id, cells: r.cells })),
    deleted_row_ids: b.deleted,
    restore_row_ids: b.restored,
    run_cleaning_on_new_rows: false,
  };
}
