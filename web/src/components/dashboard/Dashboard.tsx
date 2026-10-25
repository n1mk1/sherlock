// The Dashboard tab (App Flow §7, UI/UX brief §3.3): react-grid-layout, 12 columns, rows of 40px,
// 20px margins. Breakpoints are measured on the grid container (lg ≥ 640: 12 cols, md ≥ 480: 8,
// sm: 4). Widgets move by their handle (the whole header in Edit layout, which also adds resize
// corners); the layout saves on drop or resize and never starts the cascade.
import "react-grid-layout/css/styles.css";
import { useCallback, useMemo, useRef, useState } from "react";
import { Responsive, type Layout as GridLayout, type Layouts } from "react-grid-layout";
import { toast } from "sonner";
import { useDatacard, useWidgetActions, useWidgets } from "@/api/queries";
import type { Dataset, Layout, LayoutItem, Widget, WidgetData } from "@/api/types";
import { Button } from "@/components/ui/button";
import { useUi } from "@/state/ui";
import { AddWidgetDrawer } from "./AddWidgetDrawer";
import { ExplainDrawer } from "./ExplainDrawer";
import { WidgetShell } from "./WidgetShell";

const BREAKPOINTS = { lg: 640, md: 480, sm: 0 };
const COLS = { lg: 12, md: 8, sm: 4 };
type Bp = keyof typeof COLS;

export function Dashboard({ dataset }: { dataset: Dataset }) {
  const { data, isLoading, error } = useWidgets(dataset.id);
  const card = useDatacard(dataset.id);
  const { saveLayout } = useWidgetActions(dataset.id);
  const editLayout = useUi((s) => s.editLayout);
  const setAddOpen = useUi((s) => s.setAddWidgetOpen);
  const [explain, setExplain] = useState<{ widget: Widget; data?: WidgetData } | null>(null);
  const latest = useRef<Layouts | null>(null);
  const [measure, width] = useContainerWidth();
  const columns = useMemo(() => (card.data?.columns ?? []).map((c) => c.name), [card.data]);

  const stored = data?.layout;
  const collapsed = useMemo(() => new Set((stored?.lg ?? []).filter((i) => i.collapsed).map((i) => i.i)), [stored]);
  const gridLayouts = useMemo(() => toGrid(stored, collapsed, editLayout), [stored, collapsed, editLayout]);

  if (isLoading) return <SkeletonGrid />;
  if (error) return <p className="p-8 text-center text-muted-foreground">{(error as Error).message}</p>;
  const widgets = data?.widgets ?? [];

  const persist = (next: Layouts, collapsedIds: Set<string>) => {
    const out: Layout = { lg: [] };
    for (const bp of Object.keys(next) as Bp[]) {
      const prev = new Map((stored?.[bp] ?? stored?.lg ?? []).map((i) => [i.i, i]));
      out[bp] = next[bp].map((g) => {
        const c = collapsedIds.has(g.i);
        // A collapsed widget is drawn one row tall; keep its own height for when it expands.
        const h = c ? (prev.get(g.i)?.h ?? g.h) : g.h;
        return { i: g.i, x: g.x, y: g.y, w: g.w, h, ...(c ? { collapsed: true } : {}) } as LayoutItem;
      });
    }
    saveLayout.mutate(out, { onError: (e) => toast.error((e as Error).message) });
  };

  const toggleCollapse = (id: string) => {
    const next = new Set(collapsed);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    persist(latest.current ?? gridLayouts, next);
  };

  return (
    <div className="flex flex-col gap-4 px-4 py-4">
      {widgets.length > 0 && widgets.length < 3 && (
        <div className="mx-2 rounded-[16px] border border-dashed border-border-strong p-4 text-[13px] text-muted-foreground">
          I could only build {widgets.length} {widgets.length === 1 ? "widget" : "widgets"} for this file. Add one from chat, or tell me which columns matter.
        </div>
      )}
      {widgets.length === 0 ? (
        <div className="mx-auto flex max-w-[420px] flex-col items-center gap-3 py-16 text-center">
          <h2 className="text-[15px] font-semibold">No widgets yet</h2>
          <p className="text-muted-foreground">Widgets you add, or ask for in chat, appear here.</p>
          <Button onClick={() => setAddOpen(true)}>Add widget</Button>
        </div>
      ) : (
        <div ref={measure} className="w-full">
        {width > 0 && <Responsive
          width={width}
          className="dashboard-grid"
          layouts={gridLayouts}
          breakpoints={BREAKPOINTS}
          cols={COLS}
          rowHeight={40}
          margin={[20, 20]}
          containerPadding={[8, 0]}
          draggableHandle={editLayout ? ".widget-header" : ".widget-handle"}
          draggableCancel="button, [data-no-drag]"
          isResizable={editLayout}
          resizeHandles={["se"]}
          onLayoutChange={(_, all) => { latest.current = all; }}
          onDragStop={() => latest.current && persist(latest.current, collapsed)}
          onResizeStop={() => latest.current && persist(latest.current, collapsed)}
        >
          {widgets.map((w) => (
            <div key={w.id}>
              <WidgetShell
                widget={w}
                version={dataset.current_version}
                columns={columns}
                collapsed={collapsed.has(w.id)}
                onToggleCollapse={() => toggleCollapse(w.id)}
                onExplain={(widget, d) => setExplain({ widget, data: d })}
              />
            </div>
          ))}
        </Responsive>}
        </div>
      )}
      <ExplainDrawer widget={explain?.widget ?? null} data={explain?.data} onClose={() => setExplain(null)} />
      <AddWidgetDrawer datasetId={dataset.id} />
    </div>
  );
}

/** The grid's width from a ResizeObserver on its container. react-grid-layout's WidthProvider measured
 * 0 when the tab mounted and didn't re-measure, which left the grid on its 4-column layout. */
function useContainerWidth(): [(el: HTMLDivElement | null) => void, number] {
  const [width, setWidth] = useState(0);
  const observer = useRef<ResizeObserver | null>(null);
  const ref = useCallback((el: HTMLDivElement | null) => {
    observer.current?.disconnect();
    if (!el || typeof ResizeObserver === "undefined") return;
    observer.current = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.current.observe(el);
  }, []);
  return [ref, width];
}

/** A breakpoint's layout from lg, in lg's reading order (UI/UX brief §3.3: only lg is generated;
 * the others are derived until the user arranges them). KPI tiles go two to a row on sm. */
export function derive(lg: LayoutItem[], cols: number): LayoutItem[] {
  const ordered = [...lg].sort((a, b) => a.y - b.y || a.x - b.x);
  const out: LayoutItem[] = [];
  let x = 0, y = 0, rowH = 0;
  for (const it of ordered) {
    const kpi = it.h <= 3;
    const w = kpi ? Math.max(2, Math.round((it.w * cols) / 12)) : cols <= 4 ? cols : Math.max(4, Math.round((it.w * cols) / 12));
    if (x + w > cols) { x = 0; y += rowH; rowH = 0; }
    out.push({ ...it, x, y, w });
    x += w;
    rowH = Math.max(rowH, it.h);
  }
  return out;
}

function toGrid(layout: Layout | undefined, collapsed: Set<string>, editing: boolean): Layouts {
  const out: Layouts = {};
  for (const bp of ["lg", "md", "sm"] as Bp[]) {
    const items = layout?.[bp] ?? (layout?.lg && bp !== "lg" ? derive(layout.lg, COLS[bp]) : undefined);
    if (!items) continue;
    out[bp] = items.map((i): GridLayout => {
      const isKpi = i.h <= 3;
      const c = collapsed.has(i.i);
      return {
        i: i.i, x: i.x, y: i.y, w: i.w, h: c ? 1 : i.h,
        minW: Math.min(3, i.w), minH: c ? 1 : isKpi ? 3 : 5, isResizable: editing && !c, // sm KPI tiles are 2 wide
      };
    });
  }
  return out;
}

function SkeletonGrid() {
  return (
    <div className="grid grid-cols-2 gap-5 p-6" aria-label="Loading the dashboard">
      {[0, 1, 2, 3].map((i) => <div key={i} className="h-[300px] animate-pulse rounded-[16px] border border-border bg-card" />)}
    </div>
  );
}
