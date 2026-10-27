// The Flow tab (App Flow §12, UI/UX brief §5.10, PRD FLOW-1–FLOW-13): a React Flow canvas of story
// cards and notes joined by labelled edges, stored as JSON Canvas. Changes save within a second
// (debounced 500 ms) with the etag they were read at; a 409 or a change from the AI merges this
// tab's unsaved changes onto the server's copy. Every action has a control on screen (the status
// row, a ⋯ menu on each node, right-click) as well as a key; this tab's finished changes go on an
// undo history (`model.ts`). Selected cards are the chat's context; "Make sense of this" goes through
// the chat and comes back as a synthesis node. The viewport is remembered per dataset in this browser.
import {
  Background, BackgroundVariant, BaseEdge, EdgeLabelRenderer, getBezierPath, Handle, MiniMap, NodeResizeControl, Position,
  ReactFlow, ReactFlowProvider, ResizeControlVariant, SelectionMode, useEdgesState, useNodesState, useReactFlow, useStore,
  type Connection, type Edge, type EdgeProps, type FinalConnectionState, type NodeProps, type Viewport,
} from "@xyflow/react";
import "@xyflow/react/dist/base.css";
import {
  ArrowLeftRight, Copy, ExternalLink, HelpCircle, Minus, MoreHorizontal, Pencil, Plus, Redo2, RefreshCw, Spline, StickyNote,
  Tag, Trash2, Undo2, Workflow, X, Maximize, ClipboardPaste, BoxSelect,
} from "lucide-react";
import { createContext, lazy, Suspense, useCallback, useContext, useEffect, useMemo, useRef, useState, type DragEvent, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { canvasKey, mergeCanvas, same, saveCanvas, useCanvas, type CanvasDoc } from "@/api/canvas";
import { ApiError } from "@/api/client";
import { useWidgets } from "@/api/queries";
import { plainText, useCardActions, useCards } from "@/api/stories";
import type { Card, Dataset } from "@/api/types";
import { FlowStatus } from "@/components/flow/FlowPalette";
import {
  ARROW, CARD_W, copyOf, GRID, History, newId, NOTE_W, pasteOf, toDoc, toFlow, WIDTH,
  type CardNodeT, type Clip, type FlowEdge, type FlowNode, type NoteNodeT,
} from "@/components/flow/model";
import { EvidenceDrawer } from "@/components/stories/StoriesPanel";
import { Runs, UserTextBadges } from "@/components/stories/StoryCard";
import { Button } from "@/components/ui/button";
import { MenuContent, MenuItem, MenuRoot, MenuSeparator, MenuShortcut, MenuTrigger } from "@/components/ui/menu";
import { Tip } from "@/components/ui/tooltip";
import { motionMs } from "@/lib/motion";
import { cn } from "@/lib/utils";
import { CARD_DRAG, useFlow } from "@/state/flow";
import { useUi } from "@/state/ui";

const CardEditor = lazy(() => import("@/components/stories/CardEditor").then((m) => ({ default: m.CardEditor })));

const SAVE_MS = 500;

/** One row of a node, connection or canvas menu (the ⋯ menu and right-click show the same rows). */
type Action = { label: string; icon: ReactNode; shortcut?: string; onSelect: () => void; destructive?: boolean; disabled?: boolean };
type Target = { kind: "node"; id: string } | { kind: "edge"; id: string } | { kind: "pane"; at: { x: number; y: number } };

interface Ctx {
  datasetId: string;
  cards: Map<string, Card>;
  titles: Record<string, string>;
  editingCard: string | null;
  setEditingCard: (id: string | null) => void;
  updateNote: (id: string, text: string | null) => void; // null: an empty new note is removed
  updateEdge: (id: string, label: string | undefined) => void;
  selectEdge: (id: string) => void;
  actionsFor: (target: Target) => (Action | null)[]; // null: a separator
  evidence: (card: Card, chip: string) => void;
  pendingSource: string | null;
}
const FlowCtx = createContext<Ctx | null>(null);
const useCtx = () => useContext(FlowCtx)!;

function cardTitle(card: Card, titles: Record<string, string>) {
  if (card.kind === "overview") return "Overview";
  if (card.kind === "synthesis") return "Synthesis";
  if (card.kind === "answer") return "Answer";
  return (card.widget_id && titles[card.widget_id]) || "Story";
}

// The words React Flow says to screen readers, in Sherlock's voice (UI/UX brief §8).
const KEYS_HELP = "Press Enter or Space to select it, Delete to remove it from the canvas, and Escape to clear the selection. The arrow keys move a selected node.";
const ARIA = {
  "node.a11yDescription.default": KEYS_HELP,
  "node.a11yDescription.keyboardDisabled": KEYS_HELP,
  "node.a11yDescription.ariaLiveMessage": ({ direction, x, y }: { direction: string; x: number; y: number }) => `Moved ${direction}, to ${x}, ${y}.`,
  "edge.a11yDescription.default": "Press Enter or Space to select the connection, then Delete to remove it.",
  "handle.ariaLabel": "Connection point",
};

const editable = (t: EventTarget | null) =>
  t instanceof HTMLElement && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName));

// --- menus ---------------------------------------------------------------------------------------

function ActionItems({ items }: { items: (Action | null)[] }) {
  return items.map((a, i) => a === null
    ? <MenuSeparator key={`sep${i}`} />
    : (
      <MenuItem key={a.label} onSelect={a.onSelect} destructive={a.destructive} disabled={a.disabled}>
        {a.icon} {a.label}{a.shortcut && <MenuShortcut>{a.shortcut}</MenuShortcut>}
      </MenuItem>
    ));
}

/** The ⋯ button on a node or a selected connection: hidden until hovered, focused or selected. */
function NodeMenu({ target, name, shown }: { target: Target; name: string; shown: boolean }) {
  const { actionsFor } = useCtx();
  return (
    <MenuRoot>
      <MenuTrigger asChild>
        <button type="button" aria-label={`Menu for ${name}`} title={`Menu for ${name}`} onClick={(e) => e.stopPropagation()}
          className={cn("nodrag nopan inline-flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary",
            "focus-visible:opacity-100 focus-visible:outline-2 focus-visible:outline-ring group-hover:opacity-100 data-[state=open]:opacity-100",
            shown ? "opacity-100" : "opacity-0")}>
          <MoreHorizontal className="size-4" />
        </button>
      </MenuTrigger>
      <MenuContent><ActionItems items={actionsFor(target)} /></MenuContent>
    </MenuRoot>
  );
}

// --- nodes and edges -----------------------------------------------------------------------------

function CardNode({ id, data, selected }: NodeProps<CardNodeT>) {
  const { cards, titles, editingCard, setEditingCard, evidence, datasetId, pendingSource } = useCtx();
  const actions = useCardActions(datasetId);
  const navigate = useNavigate();
  const card = cards.get(data.cardId);
  if (!card) return null;
  const synthesis = card.kind === "synthesis";
  const err = (e: unknown) => toast.error((e as Error).message);
  const cites = card.source_card_ids?.length ?? 0;
  return (
    <div
      className={cn(
        "group rounded-[16px] border bg-card px-4 py-3.5 text-left",
        synthesis ? "border-border-strong" : "border-border",
        selected && "outline-2 outline-offset-2 outline-accent",
        pendingSource === id && "outline-2 outline-dashed outline-offset-2 outline-accent",
      )}
    >
      <Handle type="target" position={Position.Left} className="flow-handle" />
      {selected && <Resizer kind="card" />}
      <div className="-mr-2 -mt-1 mb-1 flex min-h-7 items-center gap-1.5">
        <span className={cn("min-w-0 flex-1 truncate text-[11px] font-semibold uppercase tracking-[0.08em]",
          synthesis ? "text-accent" : "text-muted-foreground")}>
          {cardTitle(card, titles)}
        </span>
        {card.status === "updating" && <RefreshCw className="size-3 animate-spin text-muted-foreground" aria-label="Updating" />}
        {(card.status === "sources_changed" || card.status === "outdated") && (
          <button type="button" className="nodrag rounded-full border border-warning px-1.5 text-[10px] text-warning"
            title={card.status === "sources_changed" ? "A number it cites changed. Click to write it again." : "Click to refresh"}
            onClick={() => actions.refresh.mutate(card.id, { onError: err })}>
            {card.status === "sources_changed" ? "sources changed" : "outdated"}
          </button>
        )}
        {card.changed_badge && <span className="rounded-full border border-warning px-1.5 text-[10px] text-warning">changed</span>}
        <UserTextBadges card={card} small />
        <NodeMenu target={{ kind: "node", id }} name={cardTitle(card, titles)} shown={!!selected} />
      </div>
      {editingCard === card.id ? (
        <div className="nodrag nowheel cursor-text">
          <Suspense fallback={<p className="text-[13px] text-muted-foreground">Opening the editor…</p>}>
            <CardEditor card={card} source={{ headline: card.headline, body: card.body }} onCancel={() => setEditingCard(null)}
              onSave={(headline, body) => actions.edit.mutate({ id: card.id, headline, body },
                { onSuccess: () => setEditingCard(null), onError: err })} />
          </Suspense>
        </div>
      ) : (
        <>
          {card.kind !== "overview" && (
            <Runs body={card.headline} facts={card.facts} onChip={(c) => evidence(card, c)}
              className="font-serif text-[15px] font-semibold leading-snug" />
          )}
          <Runs body={card.body} facts={card.facts} onChip={(c) => evidence(card, c)}
            className={cn("mt-1.5 text-[13px] leading-relaxed text-foreground-2", !synthesis && "line-clamp-6")} />
        </>
      )}
      <div className="mt-2 flex items-center gap-2 text-[12px] text-muted-foreground">
        {synthesis && <span>Cites {cites} {cites === 1 ? "card" : "cards"}</span>}
        {card.edited_by_user && <span>edited</span>}
        <span className="flex-1" />
        {card.widget_id && (
          <button type="button" className="nodrag inline-flex items-center gap-1 text-accent hover:underline"
            onClick={() => navigate(`/d/${datasetId}/dashboard?widget=${card.widget_id}`)}>
            Open widget <ExternalLink className="size-3" />
          </button>
        )}
      </div>
      <Handle type="source" position={Position.Right} className="flow-handle" />
    </div>
  );
}

function NoteNode({ id, data, selected }: NodeProps<NoteNodeT>) {
  const { updateNote, pendingSource } = useCtx();
  const [text, setText] = useState(data.text);
  useEffect(() => setText(data.text), [data.text]);
  const area = useRef<HTMLTextAreaElement>(null);
  // autoFocus loses to React Flow's own focus handling when the node mounts: focus once it's placed.
  useEffect(() => {
    if (!data.editing) return;
    const t = setTimeout(() => area.current?.focus(), 30);
    return () => clearTimeout(t);
  }, [data.editing]);
  const commit = () => updateNote(id, text.trim() ? text : data.text ? data.text : null);
  return (
    <div className={cn("group relative rounded-[14px] border border-border bg-muted py-3 pl-4 pr-9 text-[14px] leading-relaxed backdrop-blur-sm",
      "bg-[color-mix(in_srgb,var(--foreground)_5%,var(--background))]",
      selected && "outline-2 outline-offset-2 outline-accent",
      pendingSource === id && "outline-2 outline-dashed outline-offset-2 outline-accent")}>
      <Handle type="target" position={Position.Left} className="flow-handle" />
      {selected && !data.editing && <Resizer kind="note" />}
      {!data.editing && (
        <div className="absolute right-1 top-1.5">
          <NodeMenu target={{ kind: "node", id }} name="note" shown={!!selected} />
        </div>
      )}
      {data.editing ? (
        <textarea
          ref={area}
          aria-label="Note"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Escape") { setText(data.text); updateNote(id, data.text || null); }
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) commit();
            e.stopPropagation(); // Delete and Backspace edit the text, not the canvas
          }}
          rows={Math.max(3, text.split("\n").length)}
          className="nodrag nowheel w-full resize-none bg-transparent outline-none placeholder:text-muted-foreground"
          placeholder="Write a note…"
        />
      ) : (
        <p className="whitespace-pre-wrap text-foreground-2">{data.text || <span className="text-muted-foreground">Empty note</span>}</p>
      )}
      <Handle type="source" position={Position.Right} className="flow-handle" />
    </div>
  );
}

/** Widening a selected node by its right edge; the height follows the content. */
function Resizer({ kind }: { kind: "card" | "note" }) {
  const [minWidth, maxWidth] = WIDTH[kind];
  return (
    <NodeResizeControl position="right" variant={ResizeControlVariant.Line} resizeDirection="horizontal"
      minWidth={minWidth} maxWidth={maxWidth} className="flow-resize" />
  );
}

function LabeledEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, markerEnd, selected }: EdgeProps<FlowEdge>) {
  const { updateEdge, selectEdge } = useCtx();
  const [path, lx, ly] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition });
  const ai = data?.madeBy === "ai";
  const [value, setValue] = useState(data?.label ?? "");
  useEffect(() => setValue(data?.label ?? ""), [data?.label]);
  const pos = { transform: `translate(-50%, -50%) translate(${lx}px, ${ly}px)` };
  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd}
        style={{ stroke: selected || ai ? "var(--accent)" : "var(--muted-foreground)", strokeWidth: selected ? 2.25 : 1.5 }} />
      <EdgeLabelRenderer>
        {data?.editing ? (
          <input
            autoFocus
            aria-label="Connection label"
            value={value}
            placeholder="Label"
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") updateEdge(id, value.trim() || undefined);
              if (e.key === "Escape") updateEdge(id, data.label);
              e.stopPropagation();
            }}
            onBlur={() => updateEdge(id, value.trim() || undefined)}
            style={pos}
            className="nodrag nopan pointer-events-auto absolute w-36 rounded-full border border-accent bg-card px-2.5 py-0.5 text-[12px] outline-none"
          />
        ) : (data?.label || selected) ? (
          // A click on the label selects its connection, so Remove and Delete reach it.
          <div style={pos} onClick={() => selectEdge(id)}
            className={cn("nodrag nopan pointer-events-auto absolute flex items-center gap-0.5 rounded-full border bg-card text-[12px]",
              data?.label ? "py-0.5 pl-2.5" : "p-0.5", selected ? "border-accent pr-0.5" : "border-border pr-2.5")}>
            {data?.label}
            {selected && <NodeMenu target={{ kind: "edge", id }} name="connection" shown />}
          </div>
        ) : null}
      </EdgeLabelRenderer>
    </>
  );
}

const nodeTypes = { card: CardNode, note: NoteNode };
const edgeTypes = { labeled: LabeledEdge };

// --- the canvas ----------------------------------------------------------------------------------

const viewKey = (id: string) => `sherlock.flow.viewport.${id}`;
function savedViewport(id: string): Viewport | undefined {
  try {
    const v = JSON.parse(localStorage.getItem(viewKey(id)) ?? "null");
    return v && typeof v.zoom === "number" ? v : undefined;
  } catch {
    return undefined;
  }
}

// What this tab last copied, and the plain text it put on the clipboard: a paste of that same text is
// this clip; any other text becomes a new note.
let clip: (Clip & { text: string; pastes: number }) | null = null;

export function FlowTab({ dataset }: { dataset: Dataset }) {
  return (
    <ReactFlowProvider>
      <FlowCanvas dataset={dataset} />
    </ReactFlowProvider>
  );
}

function FlowCanvas({ dataset }: { dataset: Dataset }) {
  const datasetId = dataset.id;
  const qc = useQueryClient();
  const canvas = useCanvas(datasetId);
  const cardsQ = useCards(datasetId);
  const widgets = useWidgets(datasetId);
  const cardActions = useCardActions(datasetId);
  const navigate = useNavigate();
  const flow = useReactFlow<FlowNode, FlowEdge>();
  const { setSelection, setNodeCount, setCommands, connecting, setConnecting, setHistory } = useFlow();
  const { setChatDraft, setChatOpen, setFocusedWidget } = useUi();
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<FlowEdge>([]);
  const [editingCard, setEditingCard] = useState<string | null>(null);
  const [pendingSource, setPendingSource] = useState<string | null>(null);
  const [evidenceOf, setEvidenceOf] = useState<{ card: Card; chip: string } | null>(null);
  const [pointerMenu, setPointerMenu] = useState<{ x: number; y: number; target: Target; seq: number } | null>(null);
  const wrapper = useRef<HTMLDivElement>(null);
  const adding = useRef(false); // the pointer went down with Shift, Ctrl or Cmd: a click adds to the selection
  const picked = useRef<string[]>([]); // selected node IDs in the order they were picked (Connect joins the first to the second)
  // Fit the view once, on open, to a canvas that already has nodes and no remembered viewport; never
  // on the first card placed, which would zoom right in on it.
  const opening = useRef<{ fit: boolean; viewport: Viewport } | null>(null);
  if (!opening.current && canvas.data) {
    const saved = savedViewport(datasetId);
    opening.current = { fit: !saved && canvas.data.canvas.nodes.length > 0, viewport: saved ?? { x: 60, y: 40, zoom: 1 } };
  }

  const cards = useMemo(() => new Map((cardsQ.data ?? []).map((c) => [c.id, c])), [cardsQ.data]);
  const titles = useMemo(() => Object.fromEntries((widgets.data?.widgets ?? []).map((w) => [w.id, w.title])), [widgets.data]);

  // Sync state: the last document both sides agree on, its etag, and whether this tab has changes.
  const base = useRef<CanvasDoc | null>(null);
  const etag = useRef("");
  const dirty = useRef(false);
  const saving = useRef(false);
  const again = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const latest = useRef({ nodes, edges });
  latest.current = { nodes, edges };

  // Undo history: `committed` is the document as of the last recorded step (or the last copy taken
  // from the server); `pending` names the change being made, recorded once React has applied it.
  const history = useMemo(() => new History(), [datasetId]);
  const committed = useRef<CanvasDoc | null>(null);
  const pending = useRef<{ label: string; id: number } | null>(null);
  const seq = useRef(0);
  const syncHistory = useCallback(() => setHistory(history.undoLabel, history.redoLabel), [history, setHistory]);

  const apply = useCallback((doc: CanvasDoc) => {
    const next = toFlow(doc, cards, latest.current.nodes);
    setNodes(next.nodes);
    setEdges(next.edges);
    committed.current = doc;
  }, [cards, setNodes, setEdges]);

  const save = useCallback(async () => {
    if (!base.current) return;
    if (saving.current) { again.current = true; return; }
    const doc = toDoc(latest.current.nodes, latest.current.edges);
    dirty.current = false;
    if (same(doc, base.current)) return;
    saving.current = true;
    try {
      const next = await saveCanvas(datasetId, doc, etag.current);
      base.current = doc;
      etag.current = next;
      qc.setQueryData(canvasKey(datasetId), { canvas: doc, etag: next });
    } catch (e) {
      dirty.current = true;
      if (e instanceof ApiError && e.status === 409) void qc.invalidateQueries({ queryKey: canvasKey(datasetId) }); // merge, then save
      else toast.error((e as Error).message);
    } finally {
      saving.current = false;
      if (again.current) { again.current = false; void save(); }
    }
  }, [datasetId, qc]);

  const schedule = useCallback(() => {
    dirty.current = true;
    clearTimeout(timer.current);
    timer.current = setTimeout(() => void save(), SAVE_MS);
  }, [save]);
  useEffect(() => () => { clearTimeout(timer.current); if (dirty.current) void save(); }, [save]);

  /** A finished change: saved like any other, and recorded as an undo step named `label`. */
  const mark = useCallback((label: string) => {
    const id = ++seq.current;
    pending.current = { label, id };
    schedule();
    return id;
  }, [schedule]);

  useEffect(() => {
    const p = pending.current;
    if (!p || !committed.current) return;
    pending.current = null;
    const doc = toDoc(nodes, edges);
    history.push({ id: p.id, label: p.label, before: committed.current, after: doc });
    committed.current = doc;
    syncHistory();
  }, [nodes, edges, history, syncHistory]);

  const travel = useCallback((go: (current: CanvasDoc) => CanvasDoc | null) => {
    const doc = go(toDoc(latest.current.nodes, latest.current.edges));
    if (!doc) return;
    pending.current = null;
    apply(doc);
    schedule();
    syncHistory();
  }, [apply, schedule, syncHistory]);
  const undo = useCallback(() => travel((c) => history.undo(c)), [history, travel]);
  const redo = useCallback(() => travel((c) => history.redo(c)), [history, travel]);

  // A new server copy: take it as is, or merge this tab's unsaved changes onto it.
  useEffect(() => {
    const data = canvas.data;
    if (!data || !cardsQ.data) return;
    if (base.current && dirty.current) {
      const merged = mergeCanvas(base.current, toDoc(latest.current.nodes, latest.current.edges), data.canvas);
      base.current = data.canvas;
      etag.current = data.etag;
      apply(merged);
      schedule();
    } else if (data.etag !== etag.current || !base.current) {
      base.current = data.canvas;
      etag.current = data.etag;
      apply(data.canvas);
    }
  }, [canvas.data, cardsQ.data, apply, schedule]);

  // Cards deleted or restored elsewhere hide or show their nodes.
  useEffect(() => {
    setNodes((ns) => ns.map((n) => (n.type === "card" ? { ...n, hidden: !cards.has(n.data.cardId) } : n)));
  }, [cards, setNodes]);

  useEffect(() => {
    const visible = nodes.filter((n) => !n.hidden);
    const chosen = visible.filter((n) => n.selected);
    const ids = new Set(chosen.map((n) => n.id));
    picked.current = [...picked.current.filter((id) => ids.has(id)), ...chosen.map((n) => n.id).filter((id) => !picked.current.includes(id))];
    setSelection(chosen.flatMap((n) => (n.type === "card" ? [n.data.cardId] : [])), chosen.length, edges.filter((e) => e.selected).length);
    setNodeCount(visible.length);
  }, [nodes, edges, setSelection, setNodeCount]);
  useEffect(() => () => { setSelection([], 0, 0); setNodeCount(0); setConnecting(false); setHistory(null, null); },
    [setSelection, setNodeCount, setConnecting, setHistory]);

  const centre = useCallback(() => {
    const r = wrapper.current?.getBoundingClientRect();
    return flow.screenToFlowPosition({ x: (r?.left ?? 0) + (r?.width ?? 800) / 2, y: (r?.top ?? 0) + (r?.height ?? 600) / 2 });
  }, [flow]);

  const addNote = useCallback((at?: { x: number; y: number }, text = "") => {
    const p = at ?? centre();
    const note: NoteNodeT = { id: newId("nd"), type: "note", position: { x: p.x - NOTE_W / 2, y: p.y - 24 },
      data: { text, editing: !text }, width: NOTE_W, selected: true };
    setNodes((ns) => [...ns.map((n) => ({ ...n, selected: false })), note]);
    if (text) mark("Add note");
    return note.id;
  }, [centre, mark, setNodes]);

  const placeCard = useCallback((cardId: string, at?: { x: number; y: number }) => {
    const existing = latest.current.nodes.find((n) => n.type === "card" && n.data.cardId === cardId);
    if (existing) {
      setNodes((ns) => ns.map((n) => ({ ...n, selected: n.id === existing.id })));
      void flow.setCenter(existing.position.x + CARD_W / 2, existing.position.y + 80, { zoom: flow.getZoom(), duration: motionMs("base") });
      return;
    }
    let p = at ? { x: at.x - CARD_W / 2, y: at.y - 60 } : (({ x, y }) => ({ x: x - CARD_W / 2, y: y - 120 }))(centre());
    if (!at) {
      // Placed from the keyboard: below whatever card is already in the way, so none covers another. A
      // node placed a moment ago may not be measured in state yet, so ask React Flow, then assume tall.
      const size = (n: FlowNode) => n.measured ?? flow.getInternalNode(n.id)?.measured ?? {};
      for (let i = 0; i < 20; i++) {
        const q = p;
        const hit = latest.current.nodes.find((n) => !n.hidden && n.position.x < q.x + CARD_W && q.x < n.position.x + (size(n).width ?? CARD_W) &&
          n.position.y < q.y + 160 && q.y < n.position.y + (size(n).height ?? 260));
        if (!hit) break;
        p = { x: q.x, y: hit.position.y + (size(hit).height ?? 260) + 32 };
      }
    }
    const node: CardNodeT = { id: newId("nd"), type: "card", position: p, data: { cardId }, width: CARD_W };
    setNodes((ns) => [...ns, node]);
    mark("Place card");
  }, [centre, flow, mark, setNodes]);

  const updateNote = useCallback((id: string, text: string | null) => {
    const was = latest.current.nodes.find((n) => n.id === id);
    if (text === null) {
      // An empty new note goes, and so does a connection dragged out to it.
      setNodes((ns) => ns.filter((n) => n.id !== id));
      setEdges((es) => es.filter((e) => e.source !== id && e.target !== id));
      schedule();
      return;
    }
    setNodes((ns) => ns.map((n) => (n.id === id && n.type === "note" ? { ...n, data: { text, editing: false } } : n)));
    mark(was?.type === "note" && !was.data.text ? "Add note" : "Edit note");
  }, [mark, schedule, setEdges, setNodes]);

  const updateEdge = useCallback((id: string, label: string | undefined) => {
    setEdges((es) => es.map((e) => (e.id === id ? { ...e, data: { ...e.data!, label, editing: false } } : e)));
    mark("Edit label");
  }, [mark, setEdges]);

  const connect = useCallback((source: string, target: string, editing = true) => {
    if (source === target) return;
    const edge: FlowEdge = { id: newId("ed"), source, target, type: "labeled", markerEnd: ARROW,
      data: { madeBy: "user", kind: "custom", editing } };
    setEdges((es) => [...es, edge]);
    mark("Connect");
  }, [mark, setEdges]);

  const selectOnly = useCallback((nodeIds: string[], edgeIds: string[] = []) => {
    setNodes((ns) => ns.map((n) => ({ ...n, selected: nodeIds.includes(n.id) })));
    setEdges((es) => es.map((e) => ({ ...e, selected: edgeIds.includes(e.id) })));
  }, [setEdges, setNodes]);

  const remove = useCallback((nodeIds: string[], edgeIds: string[] = []) => {
    void flow.deleteElements({ nodes: nodeIds.map((id) => ({ id })), edges: edgeIds.map((id) => ({ id })) });
  }, [flow]);

  const paste = useCallback((c: Clip, offset: number) => {
    const out = pasteOf(c, latest.current.nodes, offset);
    setNodes((ns) => [...ns.map((n) => ({ ...n, selected: out.select.includes(n.id) })), ...out.nodes]);
    setEdges((es) => [...es.map((e) => ({ ...e, selected: false })), ...out.edges]);
    if (out.nodes.length || out.edges.length) mark(c === clip ? "Paste" : "Duplicate");
  }, [mark, setEdges, setNodes]);

  const duplicate = useCallback((ids?: string[]) => {
    const { nodes: ns, edges: es } = latest.current;
    const chosen = ids ? new Set(ids) : new Set(ns.filter((n) => n.selected).map((n) => n.id));
    const copy = copyOf(ns, es, (n) => n.type === "note" && chosen.has(n.id)); // a card is on the canvas once
    if (copy.nodes.length) paste(copy, 2 * GRID);
  }, [paste]);

  const zoomToSelection = useCallback(() => {
    const shown = flow.getNodes().filter((n) => !n.hidden && n.selected);
    if (shown.length) void flow.fitBounds(flow.getNodesBounds(shown), { padding: 0.3, duration: motionMs("base") });
  }, [flow]);

  // fitBounds, not fitView: React Flow 12.11 queues fitView until the next node change, which a
  // controlled canvas at rest never makes, so the button would do nothing.
  const fitView = useCallback(() => {
    const shown = flow.getNodes().filter((n) => !n.hidden);
    if (shown.length) void flow.fitBounds(flow.getNodesBounds(shown), { padding: 0.15, duration: motionMs("base") });
  }, [flow]);

  const removeSelected = useCallback(() => {
    const { nodes: ns, edges: es } = latest.current;
    remove(ns.filter((n) => n.selected && !n.hidden).map((n) => n.id), es.filter((e) => e.selected).map((e) => e.id));
  }, [remove]);

  const connectSelected = useCallback(() => {
    const [a, b] = picked.current;
    if (a && b) connect(a, b);
  }, [connect]);

  useEffect(() => {
    setCommands({ addNote: () => addNote(), fitView, placeCard, removeSelected, connectSelected, undo, redo });
    return () => setCommands(null);
  }, [addNote, fitView, placeCard, removeSelected, connectSelected, undo, redo, setCommands]);

  // Canvas keys (App Flow §12.2), only while no input, note, editor, menu or dialog has focus.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || editable(e.target) || document.querySelector('[role="dialog"], [role="menu"]')) return;
      const mod = e.ctrlKey || e.metaKey;
      const k = e.key.toLowerCase();
      if (mod && k === "z" && !e.shiftKey) undo();
      else if (mod && (k === "y" || (k === "z" && e.shiftKey))) redo();
      else if (mod && k === "a") selectOnly(latest.current.nodes.filter((n) => !n.hidden).map((n) => n.id));
      else if (mod && k === "d") duplicate();
      else if (mod && k === "0") void flow.zoomTo(1, { duration: motionMs("base") });
      else if (mod && (k === "=" || k === "+")) void flow.zoomIn({ duration: motionMs("base") });
      else if (mod && k === "-") void flow.zoomOut({ duration: motionMs("base") });
      else if (e.shiftKey && !mod && e.code === "Digit1") fitView();
      else if (e.shiftKey && !mod && e.code === "Digit2") zoomToSelection();
      else if (k === "escape" && connecting) { setConnecting(false); setPendingSource(null); }
      else if (k === "escape" && [...latest.current.nodes, ...latest.current.edges].some((x) => x.selected)) selectOnly([]);
      else return;
      e.preventDefault();
    };
    const onCopy = (e: ClipboardEvent) => {
      // Text selected on the page (a card's words) copies as text, as anywhere else.
      if (editable(e.target) || document.querySelector('[role="dialog"]') || window.getSelection()?.toString()) return;
      const { nodes: ns, edges: es } = latest.current;
      const copy = copyOf(ns, es, (n) => !!n.selected);
      if (!copy.nodes.length) return;
      const text = copy.nodes.map((n) => {
        if (n.type === "note") return n.data.text;
        const card = cards.get(n.data.cardId);
        return card ? plainText(card.headline, card.facts) : "";
      }).join("\n\n");
      clip = { ...copy, text, pastes: 0 };
      e.clipboardData?.setData("text/plain", text);
      e.preventDefault();
    };
    const onPaste = (e: ClipboardEvent) => {
      if (editable(e.target) || document.querySelector('[role="dialog"]')) return;
      const text = e.clipboardData?.getData("text/plain") ?? "";
      if (clip && text === clip.text) paste(clip, 2 * GRID * ++clip.pastes);
      else if (text.trim()) addNote(undefined, text.trim().slice(0, 5000));
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("copy", onCopy);
    window.addEventListener("paste", onPaste);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("copy", onCopy); window.removeEventListener("paste", onPaste); };
  }, [addNote, cards, connecting, duplicate, fitView, flow, paste, redo, selectOnly, setConnecting, undo, zoomToSelection]);

  const startConnect = useCallback((from: string) => { setConnecting(true); setPendingSource(from); }, [setConnecting]);

  const actionsFor = useCallback((target: Target): (Action | null)[] => {
    if (target.kind === "pane") {
      return [
        { label: "Add note here", icon: <StickyNote />, shortcut: "Double-click", onSelect: () => addNote(target.at) },
        { label: "Paste", icon: <ClipboardPaste />, shortcut: "Ctrl+V", disabled: !clip, onSelect: () => clip && paste(clip, 2 * GRID * ++clip.pastes) },
        { label: "Select all", icon: <BoxSelect />, shortcut: "Ctrl+A", onSelect: () => selectOnly(latest.current.nodes.filter((n) => !n.hidden).map((n) => n.id)) },
        { label: "Fit view", icon: <Maximize />, shortcut: "Shift+1", onSelect: fitView },
      ];
    }
    if (target.kind === "edge") {
      const edge = latest.current.edges.find((e) => e.id === target.id);
      if (!edge) return [];
      return [
        { label: "Edit label", icon: <Pencil />, shortcut: "Double-click",
          onSelect: () => setEdges((es) => es.map((x) => (x.id === edge.id ? { ...x, data: { ...x.data!, editing: true } } : x))) },
        { label: "Reverse direction", icon: <ArrowLeftRight />, onSelect: () => {
          setEdges((es) => es.map((x) => (x.id === edge.id ? { ...x, source: x.target, target: x.source } : x)));
          mark("Reverse connection");
        } },
        { label: "Remove label", icon: <Tag />, disabled: !edge.data?.label, onSelect: () => updateEdge(edge.id, undefined) },
        null,
        { label: "Delete connection", icon: <Trash2 />, shortcut: "Del", destructive: true, onSelect: () => remove([], [edge.id]) },
      ];
    }
    const node = latest.current.nodes.find((n) => n.id === target.id);
    if (!node) return [];
    if (node.type === "note") {
      return [
        { label: "Edit", icon: <Pencil />, shortcut: "Double-click",
          onSelect: () => setNodes((ns) => ns.map((n) => (n.id === node.id && n.type === "note" ? { ...n, data: { ...n.data, editing: true } } : n))) },
        { label: "Duplicate", icon: <Copy />, shortcut: "Ctrl+D", onSelect: () => duplicate([node.id]) },
        { label: "Connect from here", icon: <Spline />, onSelect: () => startConnect(node.id) },
        null,
        { label: "Delete note", icon: <Trash2 />, shortcut: "Del", destructive: true, onSelect: () => remove([node.id]) },
      ];
    }
    const card = cards.get(node.data.cardId);
    if (!card) return [];
    return [
      { label: "Edit", icon: <Pencil />, shortcut: "Double-click", onSelect: () => setEditingCard(card.id) },
      ...(card.kind !== "overview" ? [{ label: "Ask why", icon: <HelpCircle />, onSelect: () => {
        selectOnly([node.id]); // the chat's context is this card
        if (card.widget_id) setFocusedWidget(card.widget_id);
        setChatDraft(`Why ${plainText(card.headline, card.facts).replace(/\.$/, "")}?`);
        setChatOpen(true);
      } }] : []),
      ...(card.widget_id ? [{ label: "Open widget", icon: <ExternalLink />, onSelect: () => navigate(`/d/${datasetId}/dashboard?widget=${card.widget_id}`) }] : []),
      { label: "Connect from here", icon: <Spline />, onSelect: () => startConnect(node.id) },
      null,
      { label: "Remove from canvas", icon: <X />, shortcut: "Del", onSelect: () => remove([node.id]) },
      { label: "Delete card", icon: <Trash2 />, destructive: true, onSelect: () => cardActions.remove.mutate(card.id, {
        onSuccess: () => toast("Card deleted", { duration: 10_000, action: { label: "Undo", onClick: () => cardActions.restore.mutate(card.id) } }),
        onError: (e) => toast.error((e as Error).message),
      }) },
    ];
  }, [addNote, cardActions, cards, datasetId, duplicate, fitView, mark, navigate, paste, remove, selectOnly, setChatDraft, setChatOpen,
    setEdges, setFocusedWidget, setNodes, startConnect, updateEdge]);

  const ctx: Ctx = {
    datasetId, cards, titles, editingCard, setEditingCard, updateNote, updateEdge, pendingSource, actionsFor,
    selectEdge: (id) => selectOnly([], [id]),
    evidence: (card, chip) => setEvidenceOf({ card, chip }),
  };

  // Accessible names (UI/UX brief §8): what each node and connection is, in words.
  const nameOf = useCallback((n: FlowNode | undefined): string => {
    if (!n) return "a node";
    if (n.type === "note") return `note “${n.data.text.slice(0, 40)}”`;
    const card = cards.get(n.data.cardId);
    return card ? cardTitle(card, titles) : "a card";
  }, [cards, titles]);
  const shownNodes = useMemo(() => nodes.map((n) => {
    if (n.type === "note") return { ...n, ariaLabel: `Note: ${n.data.text.slice(0, 80) || "empty"}` };
    const card = cards.get(n.data.cardId);
    const headline = card && card.kind !== "overview" ? ` ${plainText(card.headline, card.facts)}` : "";
    return { ...n, ariaLabel: `Story card: ${card ? cardTitle(card, titles) : "Story"}.${headline}` };
  }), [nodes, cards, titles]);
  const shownEdges = useMemo(() => {
    const byId = new Map(nodes.map((n) => [n.id, n]));
    return edges.map((e) => ({ ...e,
      ariaLabel: `Connection from ${nameOf(byId.get(e.source))} to ${nameOf(byId.get(e.target))}${e.data?.label ? `, labelled ${e.data.label}` : ""}` }));
  }, [edges, nodes, nameOf]);

  const onDrop = (e: DragEvent) => {
    const cardId = e.dataTransfer.getData(CARD_DRAG);
    if (!cardId) return;
    e.preventDefault();
    placeCard(cardId, flow.screenToFlowPosition({ x: e.clientX, y: e.clientY }));
  };

  const openMenu = (e: { clientX: number; clientY: number; preventDefault: () => void }, target: Target) => {
    e.preventDefault();
    setPointerMenu((m) => ({ x: e.clientX, y: e.clientY, target, seq: (m?.seq ?? 0) + 1 }));
  };

  const empty = nodes.filter((n) => !n.hidden).length === 0;
  return (
    <FlowCtx.Provider value={ctx}>
      <div ref={wrapper} className="flow-canvas relative min-h-0 flex-1" onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; }} onDrop={onDrop}
        onPointerDownCapture={(e) => { adding.current = e.shiftKey || e.metaKey || e.ctrlKey; }}
        onDoubleClick={(e) => {
          // Double-clicking empty canvas adds a note there (a node's own double-click edits it).
          if ((e.target as Element).classList?.contains("react-flow__pane")) addNote(flow.screenToFlowPosition({ x: e.clientX, y: e.clientY }));
        }}>
        {canvas.data && cardsQ.data && (
          <ReactFlow<FlowNode, FlowEdge>
            nodes={shownNodes}
            edges={shownEdges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            onNodesChange={(changes) => {
              // Shift-click adds to the selection (App Flow §12.2), whatever React Flow saw of the key.
              if (adding.current) changes = changes.filter((c) => !(c.type === "select" && !c.selected));
              onNodesChange(changes);
              if (changes.some((c) => c.type === "remove")) mark("Remove");
              else if (changes.some((c) => c.type === "position" && !c.dragging && c.position)) mark("Move");
              else if (changes.some((c) => c.type === "dimensions" && c.resizing === false)) mark("Resize");
              else if (changes.some((c) => c.type === "add" || c.type === "dimensions")) schedule();
            }}
            onEdgesChange={(changes) => {
              onEdgesChange(changes);
              if (changes.some((c) => c.type === "remove")) mark("Remove");
              else if (changes.some((c) => c.type !== "select")) schedule();
            }}
            onConnect={(c: Connection) => connect(c.source, c.target)}
            onConnectEnd={(e, state: FinalConnectionState) => {
              // A connection dragged into empty canvas makes a note there, joined to where it started.
              if (state.isValid || !state.fromNode || state.toNode) return;
              const p = "changedTouches" in e ? e.changedTouches[0] : e;
              const id = addNote(flow.screenToFlowPosition({ x: p.clientX, y: p.clientY }));
              const from = state.fromNode.id;
              const edge: FlowEdge = { id: newId("ed"), type: "labeled", markerEnd: ARROW, data: { madeBy: "user", kind: "custom" },
                ...(state.fromHandle?.type === "target" ? { source: id, target: from } : { source: from, target: id }) };
              setEdges((es) => [...es, edge]);
            }}
            onReconnect={(old: Edge, c: Connection) => {
              if (c.source === c.target) return;
              setEdges((es) => es.map((e) => (e.id === old.id ? { ...e, source: c.source, target: c.target } : e)));
              mark("Reconnect");
            }}
            onNodeClick={(_, node) => {
              if (!connecting) return;
              if (!pendingSource) setPendingSource(node.id);
              else { connect(pendingSource, node.id); setPendingSource(null); setConnecting(false); }
            }}
            onNodeDoubleClick={(_, node) => {
              if (node.type === "card") setEditingCard(node.data.cardId);
              else setNodes((ns) => ns.map((n) => (n.id === node.id && n.type === "note" ? { ...n, data: { ...n.data, editing: true } } : n)));
            }}
            onEdgeDoubleClick={(_, edge) => setEdges((es) => es.map((x) => (x.id === edge.id ? { ...x, data: { ...x.data!, editing: true } } : x)))}
            onNodeContextMenu={(e, node) => openMenu(e, { kind: "node", id: node.id })}
            onEdgeContextMenu={(e, edge) => openMenu(e, { kind: "edge", id: edge.id })}
            onPaneContextMenu={(e) => openMenu(e, { kind: "pane", at: flow.screenToFlowPosition({ x: e.clientX, y: e.clientY }) })}
            onPaneClick={() => { setPendingSource(null); }}
            onDelete={({ nodes: gone, edges: goneEdges }) => {
              if (!gone.length && !goneEdges.length) return;
              // The node picked first in Connect mode is gone: the pick goes too.
              if (pendingSource && gone.some((n) => n.id === pendingSource)) setPendingSource(null);
              const step = mark("Remove");
              const what = gone.length ? `${gone.length} ${gone.length === 1 ? "item" : "items"}` : `${goneEdges.length} ${goneEdges.length === 1 ? "connection" : "connections"}`;
              toast(`Removed ${what} from the canvas`, {
                description: gone.some((n) => n.type === "card") ? "Cards stay in the palette." : undefined,
                duration: 10_000,
                action: { label: "Undo", onClick: () => travel((c) => history.revert(step, c)) },
              });
            }}
            onMoveEnd={(_, v) => { try { localStorage.setItem(viewKey(datasetId), JSON.stringify(v)); } catch { /* private mode */ } }}
            defaultViewport={opening.current?.viewport}
            fitView={opening.current?.fit}
            fitViewOptions={{ padding: 0.15 }}
            deleteKeyCode={["Delete", "Backspace"]}
            multiSelectionKeyCode={["Shift", "Meta", "Control"]}
            selectionKeyCode="Shift"
            selectionMode={SelectionMode.Partial}
            zoomOnDoubleClick={false}
            snapToGrid
            snapGrid={[GRID, GRID]}
            ariaLabelConfig={ARIA}
            minZoom={0.2}
            maxZoom={2}
            proOptions={{ hideAttribution: true }}
            className={cn(connecting && "cursor-crosshair")}
          >
            <Background variant={BackgroundVariant.Dots} gap={GRID} size={1.2} color="var(--border-strong)" />
            <MiniMap pannable zoomable position="bottom-right" ariaLabel="Canvas overview"
              nodeColor={(n) => (n.type === "card" ? "var(--border-strong)" : "var(--muted-foreground)")}
              style={{ width: 132, height: 84 }} />
            <ViewControls />
          </ReactFlow>
        )}
        <FlowStatus />
        {connecting && (
          <div role="status" className="pointer-events-none absolute left-1/2 top-3 -translate-x-1/2 rounded-full border border-accent bg-card px-3 py-1 text-[12px]">
            {pendingSource ? "Now click the node to connect it to" : "Click the first node, then the second"}
          </div>
        )}
        {empty && canvas.data && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-8">
            <div className="flex max-w-[420px] flex-col items-center text-center">
              <Workflow className="mb-3 size-6 text-muted-foreground" aria-hidden />
              <h2 className="text-[15px] font-semibold">The canvas is empty</h2>
              <p className="mt-1 text-[14px] text-muted-foreground">
                Drag story cards here from the palette, or add a note. Select two or more cards and ask Sherlock to make sense of them.
              </p>
              <Button variant="primary" className="pointer-events-auto mt-4" onClick={() => addNote()}><Plus /> Add note</Button>
            </div>
          </div>
        )}
        {pointerMenu && (
          <MenuRoot key={pointerMenu.seq} defaultOpen onOpenChange={(open) => { if (!open) setPointerMenu(null); }}>
            <MenuTrigger asChild>
              <span aria-hidden className="pointer-events-none fixed size-0" style={{ left: pointerMenu.x, top: pointerMenu.y }} />
            </MenuTrigger>
            <MenuContent align="start"><ActionItems items={actionsFor(pointerMenu.target)} /></MenuContent>
          </MenuRoot>
        )}
      </div>
      <EvidenceDrawer value={evidenceOf} onClose={() => setEvidenceOf(null)} />
    </FlowCtx.Provider>
  );
}

/** Bottom-left: Undo and Redo, then zoom out, the zoom level (a click resets it to 100%) and zoom in. */
function ViewControls() {
  const flow = useReactFlow();
  const zoom = useStore((s) => s.transform[2]);
  const { commands, undoLabel, redoLabel } = useFlow();
  const ms = () => ({ duration: motionMs("base") });
  const icon = "size-8 rounded-full text-muted-foreground hover:text-foreground";
  return (
    <div className="absolute bottom-4 left-4 z-10 flex items-center rounded-full border border-border bg-card p-0.5">
      <Tip label={undoLabel ? `Undo ${undoLabel.toLowerCase()}` : "Nothing to undo"} shortcut="Ctrl+Z">
        <Button variant="ghost" size="icon" className={icon} aria-label={undoLabel ? `Undo ${undoLabel.toLowerCase()}` : "Undo"}
          disabled={!undoLabel} onClick={() => commands?.undo()}><Undo2 /></Button>
      </Tip>
      <Tip label={redoLabel ? `Redo ${redoLabel.toLowerCase()}` : "Nothing to redo"} shortcut="Ctrl+Shift+Z">
        <Button variant="ghost" size="icon" className={icon} aria-label={redoLabel ? `Redo ${redoLabel.toLowerCase()}` : "Redo"}
          disabled={!redoLabel} onClick={() => commands?.redo()}><Redo2 /></Button>
      </Tip>
      <span className="mx-1 h-4 w-px bg-border" aria-hidden />
      <Tip label="Zoom out" shortcut="Ctrl+−">
        <Button variant="ghost" size="icon" className={icon} aria-label="Zoom out" onClick={() => void flow.zoomOut(ms())}><Minus /></Button>
      </Tip>
      <Tip label="Reset to 100%" shortcut="Ctrl+0">
        <Button variant="ghost" className="h-8 w-14 rounded-full px-0 font-mono text-[12px] text-muted-foreground hover:text-foreground"
          aria-label={`Zoom ${Math.round(zoom * 100)}%, reset to 100%`} onClick={() => void flow.zoomTo(1, ms())}>
          {Math.round(zoom * 100)}%
        </Button>
      </Tip>
      <Tip label="Zoom in" shortcut="Ctrl+=">
        <Button variant="ghost" size="icon" className={icon} aria-label="Zoom in" onClick={() => void flow.zoomIn(ms())}><Plus /></Button>
      </Tip>
    </div>
  );
}
