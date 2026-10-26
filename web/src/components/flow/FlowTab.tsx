// The Flow tab (App Flow §12, UI/UX brief §5.10, PRD FLOW-1–FLOW-6): a React Flow canvas of story
// cards and notes joined by labelled edges, stored as JSON Canvas. Changes save within a second
// (debounced 500 ms) with the etag they were read at; a 409 or a change from the AI merges this
// tab's unsaved changes onto the server's copy. Selected cards are the chat's context; "Make sense
// of this" goes through the chat and comes back as a synthesis node. The viewport is remembered per
// dataset in this browser.
import {
  Background, BackgroundVariant, BaseEdge, EdgeLabelRenderer, getBezierPath, Handle, MarkerType, MiniMap, Position,
  ReactFlow, ReactFlowProvider, useEdgesState, useNodesState, useReactFlow,
  type Connection, type Edge, type EdgeProps, type Node, type NodeProps, type Viewport,
} from "@xyflow/react";
import "@xyflow/react/dist/base.css";
import { ExternalLink, Minus, Plus, RefreshCw } from "lucide-react";
import { createContext, lazy, Suspense, useCallback, useContext, useEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { canvasKey, mergeCanvas, same, saveCanvas, useCanvas, type CanvasDoc } from "@/api/canvas";
import { ApiError } from "@/api/client";
import { useWidgets } from "@/api/queries";
import { useCardActions, useCards } from "@/api/stories";
import type { Card, Dataset } from "@/api/types";
import { FlowStatus } from "@/components/flow/FlowPalette";
import { EvidenceDrawer } from "@/components/stories/StoriesPanel";
import { Runs, UserTextBadges } from "@/components/stories/StoryCard";
import { cn } from "@/lib/utils";
import { CARD_DRAG, useFlow } from "@/state/flow";

const CardEditor = lazy(() => import("@/components/stories/CardEditor").then((m) => ({ default: m.CardEditor })));

const CARD_W = 240;
const NOTE_W = 220;
const SAVE_MS = 500;

type CardData = { cardId: string };
type NoteData = { text: string; editing?: boolean };
type CardNodeT = Node<CardData, "card">;
type NoteNodeT = Node<NoteData, "note">;
type FlowNode = CardNodeT | NoteNodeT;
type EdgeData = { label?: string; madeBy: "user" | "ai"; kind: NonNullable<CanvasDoc["edges"][number]["sherlock"]>["kind"]; editing?: boolean };
type FlowEdge = Edge<EdgeData, "labeled">;

interface Ctx {
  datasetId: string;
  cards: Map<string, Card>;
  titles: Record<string, string>;
  editingCard: string | null;
  setEditingCard: (id: string | null) => void;
  updateNote: (id: string, text: string | null) => void; // null: an empty new note is removed
  updateEdge: (id: string, label: string | undefined) => void;
  evidence: (card: Card, chip: string) => void;
  pendingSource: string | null;
}
const FlowCtx = createContext<Ctx | null>(null);
const useCtx = () => useContext(FlowCtx)!;

// --- conversions ---------------------------------------------------------------------------------

function toFlow(doc: CanvasDoc, cards: Map<string, Card>, prev: FlowNode[]): { nodes: FlowNode[]; edges: FlowEdge[] } {
  const selected = new Set(prev.filter((n) => n.selected).map((n) => n.id));
  const nodes: FlowNode[] = doc.nodes.map((n) => {
    const base = { id: n.id, position: { x: n.x, y: n.y }, selected: selected.has(n.id) };
    if (n.sherlock?.card_id) {
      // A soft-deleted card's node stays hidden, so restoring the card puts it back in place.
      return { ...base, type: "card", data: { cardId: n.sherlock.card_id }, hidden: !cards.has(n.sherlock.card_id),
        style: { width: CARD_W } } as CardNodeT;
    }
    return { ...base, type: "note", data: { text: n.text ?? "" }, style: { width: NOTE_W } } as NoteNodeT;
  });
  const edges: FlowEdge[] = doc.edges.map((e) => ({
    id: e.id, source: e.fromNode, target: e.toNode, type: "labeled",
    data: { label: e.label, madeBy: e.sherlock?.made_by ?? "user", kind: e.sherlock?.kind ?? "custom" },
    markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
  }));
  return { nodes, edges };
}

function toDoc(all: FlowNode[], allEdges: FlowEdge[]): CanvasDoc {
  // A new note still being written for the first time isn't saved until it has words.
  const nodes = all.filter((n) => !(n.type === "note" && n.data.editing && !n.data.text));
  const kept = new Set(nodes.map((n) => n.id));
  const edges = allEdges.filter((e) => kept.has(e.source) && kept.has(e.target));
  return {
    nodes: nodes.map((n) => {
      const w = Math.round(n.measured?.width ?? (n.type === "card" ? CARD_W : NOTE_W));
      const h = Math.round(n.measured?.height ?? (n.type === "card" ? 170 : 80));
      const base = { id: n.id, type: "text" as const, x: Math.round(n.position.x), y: Math.round(n.position.y), width: w, height: h };
      return n.type === "card" ? { ...base, text: "", sherlock: { card_id: n.data.cardId } } : { ...base, text: n.data.text };
    }),
    edges: edges.map((e) => ({
      id: e.id, fromNode: e.source, toNode: e.target, ...(e.data?.label ? { label: e.data.label } : {}),
      sherlock: { made_by: e.data?.madeBy ?? "user", kind: e.data?.kind ?? "custom" },
    })),
  };
}

const newId = (p: string) => `${p}_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;

function cardTitle(card: Card, titles: Record<string, string>) {
  if (card.kind === "overview") return "Overview";
  if (card.kind === "synthesis") return "Synthesis";
  if (card.kind === "answer") return "Answer";
  return (card.widget_id && titles[card.widget_id]) || "Story";
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
        "rounded-[16px] border bg-card px-4 py-3.5 text-left shadow-[0_1px_2px_rgba(0,0,0,0.04)]",
        synthesis ? "border-border-strong" : "border-border",
        selected && "outline-2 outline-offset-2 outline-accent",
        pendingSource === id && "outline-2 outline-dashed outline-offset-2 outline-accent",
      )}
    >
      <Handle type="target" position={Position.Left} className="flow-handle" />
      <div className="mb-1 flex items-center gap-1.5">
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
    <div className={cn("rounded-[14px] border border-border bg-muted px-4 py-3 text-[14px] leading-relaxed backdrop-blur-sm",
      "bg-[color-mix(in_srgb,var(--foreground)_5%,var(--background))]",
      selected && "outline-2 outline-offset-2 outline-accent",
      pendingSource === id && "outline-2 outline-dashed outline-offset-2 outline-accent")}>
      <Handle type="target" position={Position.Left} className="flow-handle" />
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

function LabeledEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, data, markerEnd, selected }: EdgeProps<FlowEdge>) {
  const { updateEdge } = useCtx();
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
        ) : data?.label ? (
          <div style={pos} className={cn("nodrag nopan pointer-events-auto absolute rounded-full border bg-card px-2.5 py-0.5 text-[12px]",
            selected ? "border-accent" : "border-border")}>
            {data.label}
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
  const flow = useReactFlow<FlowNode, FlowEdge>();
  const { setSelection, setNodeCount, setCommands, connecting, setConnecting } = useFlow();
  const [nodes, setNodes, onNodesChange] = useNodesState<FlowNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<FlowEdge>([]);
  const [editingCard, setEditingCard] = useState<string | null>(null);
  const [pendingSource, setPendingSource] = useState<string | null>(null);
  const [evidenceOf, setEvidenceOf] = useState<{ card: Card; chip: string } | null>(null);
  const wrapper = useRef<HTMLDivElement>(null);
  const adding = useRef(false); // the pointer went down with Shift, Ctrl or Cmd: a click adds to the selection
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

  const apply = useCallback((doc: CanvasDoc) => {
    const next = toFlow(doc, cards, latest.current.nodes);
    setNodes(next.nodes);
    setEdges(next.edges);
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
    const picked = visible.filter((n) => n.selected);
    setSelection(picked.flatMap((n) => (n.type === "card" ? [n.data.cardId] : [])), picked.length);
    setNodeCount(visible.length);
  }, [nodes, setSelection, setNodeCount]);
  useEffect(() => () => { setSelection([], 0); setNodeCount(0); setConnecting(false); }, [setSelection, setNodeCount, setConnecting]);

  const centre = useCallback(() => {
    const r = wrapper.current?.getBoundingClientRect();
    return flow.screenToFlowPosition({ x: (r?.left ?? 0) + (r?.width ?? 800) / 2, y: (r?.top ?? 0) + (r?.height ?? 600) / 2 });
  }, [flow]);

  const addNote = useCallback(() => {
    const p = centre();
    const note: NoteNodeT = { id: newId("nd"), type: "note", position: { x: p.x - NOTE_W / 2, y: p.y - 40 },
      data: { text: "", editing: true }, style: { width: NOTE_W }, selected: true };
    setNodes((ns) => [...ns.map((n) => ({ ...n, selected: false })), note]);
  }, [centre, setNodes]);

  const placeCard = useCallback((cardId: string, at?: { x: number; y: number }) => {
    const existing = latest.current.nodes.find((n) => n.type === "card" && n.data.cardId === cardId);
    if (existing) {
      setNodes((ns) => ns.map((n) => ({ ...n, selected: n.id === existing.id })));
      void flow.setCenter(existing.position.x + CARD_W / 2, existing.position.y + 80, { zoom: flow.getZoom(), duration: 300 });
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
    const node: CardNodeT = { id: newId("nd"), type: "card", position: p, data: { cardId }, style: { width: CARD_W } };
    setNodes((ns) => [...ns, node]);
    schedule();
  }, [centre, flow, schedule, setNodes]);

  useEffect(() => {
    // fitBounds, not fitView: React Flow 12.11 queues fitView until the next node change, which a
    // controlled canvas at rest never makes, so the button would do nothing.
    const fitView = () => {
      const shown = flow.getNodes().filter((n) => !n.hidden);
      if (shown.length) void flow.fitBounds(flow.getNodesBounds(shown), { padding: 0.15, duration: 300 });
    };
    setCommands({ addNote, fitView, placeCard });
    return () => setCommands(null);
  }, [addNote, flow, placeCard, setCommands]);

  const updateNote = useCallback((id: string, text: string | null) => {
    if (text === null) setNodes((ns) => ns.filter((n) => n.id !== id));
    else setNodes((ns) => ns.map((n) => (n.id === id && n.type === "note" ? { ...n, data: { text, editing: false } } : n)));
    schedule();
  }, [schedule, setNodes]);

  const updateEdge = useCallback((id: string, label: string | undefined) => {
    setEdges((es) => es.map((e) => (e.id === id ? { ...e, data: { ...e.data!, label, editing: false } } : e)));
    schedule();
  }, [schedule, setEdges]);

  const connect = useCallback((source: string, target: string) => {
    if (source === target) return;
    const edge: FlowEdge = { id: newId("ed"), source, target, type: "labeled", markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
      data: { madeBy: "user", kind: "custom", editing: true } };
    setEdges((es) => [...es, edge]);
    schedule();
  }, [schedule, setEdges]);

  const ctx: Ctx = {
    datasetId, cards, titles, editingCard, setEditingCard, updateNote, updateEdge, pendingSource,
    evidence: (card, chip) => setEvidenceOf({ card, chip }),
  };

  const onDrop = (e: DragEvent) => {
    const cardId = e.dataTransfer.getData(CARD_DRAG);
    if (!cardId) return;
    e.preventDefault();
    placeCard(cardId, flow.screenToFlowPosition({ x: e.clientX, y: e.clientY }));
  };

  const empty = nodes.filter((n) => !n.hidden).length === 0;
  return (
    <FlowCtx.Provider value={ctx}>
      <div ref={wrapper} className="flow-canvas relative min-h-0 flex-1" onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; }} onDrop={onDrop}
        onPointerDownCapture={(e) => { adding.current = e.shiftKey || e.metaKey || e.ctrlKey; }}>
        {canvas.data && cardsQ.data && (
          <ReactFlow<FlowNode, FlowEdge>
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            onNodesChange={(changes) => {
              // Shift-click adds to the selection (App Flow §12.2), whatever React Flow saw of the key.
              if (adding.current) changes = changes.filter((c) => !(c.type === "select" && !c.selected));
              onNodesChange(changes);
              if (changes.some((c) => c.type === "remove" || c.type === "add" || (c.type === "position" && !c.dragging) || c.type === "dimensions")) schedule();
            }}
            onEdgesChange={(changes) => {
              onEdgesChange(changes);
              if (changes.some((c) => c.type !== "select")) schedule();
            }}
            onConnect={(c: Connection) => connect(c.source, c.target)}
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
            onPaneClick={() => { setPendingSource(null); }}
            onDelete={({ nodes: gone, edges: goneEdges }) => {
              if (!gone.length && !goneEdges.length) return;
              const what = gone.length ? `${gone.length} ${gone.length === 1 ? "item" : "items"}` : `${goneEdges.length} ${goneEdges.length === 1 ? "connection" : "connections"}`;
              toast(`Removed ${what} from the canvas`, {
                description: gone.some((n) => n.type === "card") ? "Cards stay in the palette." : undefined,
                duration: 10_000,
                action: { label: "Undo", onClick: () => {
                  setNodes((ns) => [...ns, ...(gone as FlowNode[]).filter((g) => !ns.some((n) => n.id === g.id))]);
                  setEdges((es) => [...es, ...(goneEdges as FlowEdge[]).filter((g) => !es.some((x) => x.id === g.id))]);
                  schedule();
                } },
              });
            }}
            onMoveEnd={(_, v) => { try { localStorage.setItem(viewKey(datasetId), JSON.stringify(v)); } catch { /* private mode */ } }}
            defaultViewport={opening.current?.viewport}
            fitView={opening.current?.fit}
            fitViewOptions={{ padding: 0.15 }}
            deleteKeyCode={["Delete", "Backspace"]}
            multiSelectionKeyCode={["Shift", "Meta", "Control"]}
            selectionKeyCode={null}
            minZoom={0.2}
            maxZoom={2}
            proOptions={{ hideAttribution: true }}
            className={cn(connecting && "cursor-crosshair")}
          >
            <Background variant={BackgroundVariant.Dots} gap={22} size={1.2} color="var(--border-strong)" />
            <MiniMap pannable zoomable position="bottom-right" ariaLabel="Canvas overview"
              nodeColor={(n) => (n.type === "card" ? "var(--border-strong)" : "var(--muted-foreground)")}
              style={{ width: 132, height: 84 }} />
            <Zoom />
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
            <div className="max-w-[360px] text-center">
              <h2 className="text-[15px] font-semibold">The canvas is empty</h2>
              <p className="mt-1 text-[14px] text-muted-foreground">
                Drag story cards here from the palette, or add a note. Select two or more cards and ask Sherlock to make sense of them.
              </p>
            </div>
          </div>
        )}
      </div>
      <EvidenceDrawer value={evidenceOf} onClose={() => setEvidenceOf(null)} />
    </FlowCtx.Provider>
  );
}

function Zoom() {
  const flow = useReactFlow();
  return (
    <div className="absolute bottom-4 left-4 z-10 flex rounded-full border border-border bg-card p-0.5">
      <button type="button" aria-label="Zoom out" onClick={() => void flow.zoomOut({ duration: 200 })}
        className="inline-flex size-8 items-center justify-center rounded-full text-muted-foreground hover:bg-secondary hover:text-foreground">
        <Minus className="size-4" />
      </button>
      <button type="button" aria-label="Zoom in" onClick={() => void flow.zoomIn({ duration: 200 })}
        className="inline-flex size-8 items-center justify-center rounded-full text-muted-foreground hover:bg-secondary hover:text-foreground">
        <Plus className="size-4" />
      </button>
    </div>
  );
}
