// The Flow palette (App Flow §12.1, UI/UX brief §5.10): the right panel on the Flow tab. Search, then
// every story card as a row to drag onto the canvas (or press Enter to place it in the middle), each
// marked "on canvas" or "not placed"; then "Try asking"; then Export.
import { GripVertical } from "lucide-react";
import { useMemo, useState } from "react";
import { useMatch } from "react-router-dom";
import { useCanvas } from "@/api/canvas";
import { useWidgets } from "@/api/queries";
import { plainText, useCards } from "@/api/stories";
import type { Card } from "@/api/types";
import { CARD_DRAG, useFlow } from "@/state/flow";
import { useUi } from "@/state/ui";

function rowTitle(card: Card, titles: Record<string, string>) {
  if (card.kind === "overview") return "Overview";
  if (card.widget_id && titles[card.widget_id]) return titles[card.widget_id];
  return plainText(card.headline, card.facts).slice(0, 60) || (card.kind === "synthesis" ? "Synthesis" : "Answer");
}

export function FlowPalette() {
  const match = useMatch("/d/:datasetId/flow");
  const datasetId = match?.params.datasetId ?? "";
  const cards = useCards(datasetId);
  const widgets = useWidgets(datasetId);
  const canvas = useCanvas(datasetId);
  const commands = useFlow((s) => s.commands);
  const { setExportOpen, setChatDraft } = useUi();
  const [query, setQuery] = useState("");
  const titles = useMemo(() => Object.fromEntries((widgets.data?.widgets ?? []).map((w) => [w.id, w.title])), [widgets.data]);
  const placed = new Set((canvas.data?.canvas.nodes ?? []).flatMap((n) => (n.sherlock?.card_id ? [n.sherlock.card_id] : [])));
  const rows = (cards.data ?? []).filter((c) => rowTitle(c, titles).toLowerCase().includes(query.trim().toLowerCase()));
  const firstColumn = (cards.data ?? []).flatMap((c) => c.body.blocks.flatMap((b) => b.runs))
    .find((r) => r.type === "label" && r.ref.startsWith("column:"));
  const tries = ["Make sense of this", `What do these cards say about ${firstColumn?.type === "label" ? firstColumn.text : "the data"}?`];

  return (
    <section aria-labelledby="palette-title" className="flex h-full flex-col gap-3 overflow-y-auto p-4">
      <h2 id="palette-title" className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Story cards</h2>
      <label className="sr-only" htmlFor="palette-search">Search cards</label>
      <input id="palette-search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search cards"
        className="h-10 rounded-[10px] border border-border bg-card px-3 text-[14px] outline-none focus:border-border-strong" />
      {cards.data && cards.data.length === 0 && (
        <p className="text-[13px] text-muted-foreground">Story cards appear here once the dashboard's stories are written.</p>
      )}
      <p id="palette-hint" className="sr-only">Drag onto the canvas, or press Enter to place it in the middle.</p>
      <ul className="flex flex-col gap-2">
        {rows.map((c) => (
          <li key={c.id}>
            <div
              role="button"
              tabIndex={0}
              draggable
              onDragStart={(e) => { e.dataTransfer.setData(CARD_DRAG, c.id); e.dataTransfer.effectAllowed = "move"; }}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); commands?.placeCard(c.id); } }}
              onDoubleClick={() => commands?.placeCard(c.id)}
              aria-label={`${rowTitle(c, titles)}, ${placed.has(c.id) ? "on canvas" : "not placed"}`}
              aria-describedby="palette-hint"
              title="Drag onto the canvas, or press Enter to place it"
              className="flex cursor-grab items-center gap-2 rounded-[12px] border border-border bg-card px-3 py-2.5 text-[14px] hover:border-border-strong focus-visible:outline-2 focus-visible:outline-ring active:cursor-grabbing"
            >
              <GripVertical className="size-4 shrink-0 text-muted-foreground" aria-hidden />
              <span className="min-w-0 flex-1 truncate">{rowTitle(c, titles)}</span>
              <span className="shrink-0 text-[12px] text-muted-foreground">{placed.has(c.id) ? "on canvas" : "not placed"}</span>
            </div>
          </li>
        ))}
      </ul>
      <div className="rounded-[14px] border border-border bg-card p-3.5">
        <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Try asking</h3>
        <ul className="flex flex-col gap-1.5 text-[14px]">
          {tries.map((t) => (
            <li key={t}>
              <button type="button" className="text-left hover:text-accent" onClick={() => setChatDraft(t)}>“{t}”</button>
            </li>
          ))}
        </ul>
      </div>
      <div className="mt-auto flex flex-col gap-1.5 pt-4">
        <h3 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Export</h3>
        <button type="button" onClick={() => setExportOpen(true)} className="self-start text-[14px] text-accent underline-offset-4 hover:underline">
          Notebook (.ipynb)
        </button>
        <span className="text-[14px] text-muted-foreground">Obsidian (.canvas) · P1</span>
      </div>
    </section>
  );
}

/** "Story canvas · 6 nodes · 3 selected" and, with two or more cards selected, "Make sense of this",
 * at the canvas's top left so the header never changes width. */
export function FlowStatus() {
  const { selectedCount, nodeCount, selectedCardIds } = useFlow();
  const sendChat = useUi((s) => s.sendChat);
  return (
    <div className="absolute left-4 top-3 z-10 flex items-center gap-3">
      <p role="status" className="text-[13px] text-muted-foreground">
        Story canvas · {nodeCount} {nodeCount === 1 ? "node" : "nodes"}{selectedCount ? ` · ${selectedCount} selected` : ""}
      </p>
      {selectedCardIds.length >= 2 && (
        <button type="button" onClick={() => sendChat("Make sense of this")}
          className="inline-flex h-7 items-center rounded-md bg-primary px-3 text-[13px] font-medium text-primary-foreground hover:brightness-110">
          Make sense of this
        </button>
      )}
    </div>
  );
}

export function FlowActions() {
  const { commands, connecting, setConnecting } = useFlow();
  return (
    <>
      <button type="button" onClick={() => commands?.addNote()}
        className="inline-flex h-7 items-center rounded-md border border-border bg-secondary px-3 text-[13px] font-medium hover:bg-muted">Add note</button>
      <button type="button" aria-pressed={connecting} onClick={() => setConnecting(!connecting)}
        className={`inline-flex h-7 items-center rounded-md px-3 text-[13px] font-medium hover:bg-secondary ${connecting ? "bg-secondary text-accent" : ""}`}>
        Connect
      </button>
      <button type="button" onClick={() => commands?.fitView()}
        className="inline-flex h-7 items-center rounded-md px-3 text-[13px] font-medium hover:bg-secondary">Fit view</button>
    </>
  );
}
