// The widget shell (UI/UX brief §4.3, App Flow §7.2): header (handle, title, scope chip, menu), body
// (chart or table), footer (version, "How do you know?", status). States: loading (skeleton), ready,
// updating (dimmed with a progress line while a filter re-queries), error (message, Retry, Show
// query), collapsed (header only).
import { ChevronDown, ChevronUp, Copy, GripVertical, LayoutGrid, MoreHorizontal, Table2, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { filterParam, useWidgetActions, useWidgetData } from "@/api/queries";
import { useCards } from "@/api/stories";
import type { FilterClause, ViewType, Widget, WidgetData } from "@/api/types";
import { WidgetChart } from "@/components/charts/adapter";
import { Button } from "@/components/ui/button";
import { MenuCheck, MenuContent, MenuItem, MenuRoot, MenuSeparator, MenuTrigger, SubMenu } from "@/components/ui/menu";
import { cn } from "@/lib/utils";
import { useFilters, useGlobalFilter } from "@/state/filters";
import { useUi } from "@/state/ui";

const VIEW_LABELS: Record<string, string> = {
  bar: "Bar", line: "Line", area: "Area", pie: "Pie", ring: "Ring", kpi: "KPI tile", table: "Table",
  histogram: "Histogram", heatmap: "Heatmap", box: "Box plot", scatter: "Scatter",
};

/** Views that can draw this result (the menu's Change view). */
export function compatibleViews(data: WidgetData | undefined): ViewType[] {
  if (!data) return ["table"];
  const names = data.columns.map((c) => c.name);
  if (["q1", "median", "q3"].every((n) => names.includes(n))) return ["box", "table"];
  if (names.includes("bin_start")) return ["histogram", "bar", "table"];
  const numeric = data.columns.some((_, i) => i > 0 && data.rows.some((r) => typeof r[i] === "number"));
  if (data.row_count === 1 || data.columns.length === 1) return ["kpi", "table"];
  const dated = data.columns[0]?.type.startsWith("DATE") || data.columns[0]?.type.startsWith("TIMESTAMP");
  if (!numeric) return ["table"];
  return dated ? ["line", "area", "bar", "table"] : ["bar", "pie", "ring", "table"];
}

export function WidgetShell({ widget, version, columns, collapsed, onToggleCollapse, onExplain }: {
  widget: Widget;
  version: number;
  columns: string[]; // the dataset's columns, to know what a click can filter on
  collapsed: boolean;
  onToggleCollapse: () => void;
  onExplain: (widget: Widget, data?: WidgetData) => void;
}) {
  const filter = useGlobalFilter(widget.dataset_id);
  const toggle = useFilters((s) => s.toggle);
  const editLayout = useUi((s) => s.editLayout);
  const setFocused = useUi((s) => s.setFocusedWidget);
  const link = useLinking(widget);
  const inherits = widget.spec.scope.rows.inherit_global_filters !== false;
  // The column a click filters on: the spec's category column (the result's first column is
  // checked once the data is in).
  const specSource = columns.includes(String(widget.spec.scope.columns.x)) ? String(widget.spec.scope.columns.x) : undefined;
  // A chart doesn't filter itself by its own category: its clicked bar keeps the accent and the
  // others fade (UI/UX brief §4.4).
  const ownFilter = !!filter && filter.col === specSource;
  const applied = inherits && !ownFilter ? filter : null;
  const query = useWidgetData(widget, filterParam(applied), version);
  const actions = useWidgetActions(widget.dataset_id);
  const [asTable, setAsTable] = useState(false);
  const data = query.data;

  const source = specSource ?? (data && columns.includes(data.columns[0]?.name) ? data.columns[0].name : undefined);
  const selected = filter && source && filter.col === source ? String(filter.value) : null;
  const onSelect = source && ["bar", "pie", "ring"].includes(widget.spec.view.type)
    ? (value: unknown) => toggle(widget.dataset_id, { col: source, op: "eq", value } as FilterClause)
    : undefined;

  const remove = () =>
    actions.remove.mutate(widget.id, {
      onSuccess: () =>
        toast("Widget deleted", { duration: 10_000, action: { label: "Undo", onClick: () => actions.restore.mutate(widget.id) } }),
      onError: (e) => toast.error((e as Error).message),
    });
  const changeView = (type: ViewType) =>
    actions.patch.mutate(
      { id: widget.id, body: { view: { type, options: widget.spec.view.options } } },
      { onError: (e) => toast.error((e as Error).message) },
    );
  // Updating: a filter re-query, or the cascade re-running this widget after a new version (App Flow §16).
  const inCascade = useUi((s) => s.cascade[widget.dataset_id]?.widgetIds.includes(widget.id) ?? false);
  const updating = (query.isFetching && !!query.data) || inCascade;

  return (
    <article
      ref={link.ref}
      data-widget-id={widget.id}
      className={cn(
        "@container group flex h-full flex-col overflow-hidden rounded-[16px] border border-border bg-card",
        "transition-[border-color,box-shadow] duration-[var(--duration-fast)] hover:border-accent focus-within:border-border-strong",
        link.state === "hovered" && "border-accent shadow-[var(--spotlight-shadow)]",
        link.state === "related" && "border-[color-mix(in_srgb,var(--accent)_45%,transparent)]",
        link.state === "flash" && "border-accent shadow-[0_0_0_3px_var(--spotlight)]",
      )}
      onPointerDown={() => setFocused(widget.id)}
      onMouseEnter={link.enter}
      onMouseLeave={link.leave}
      aria-label={widget.title}
    >
      <header className={cn("widget-header flex h-10 shrink-0 items-center gap-1.5 px-2", editLayout && "cursor-grab")}>
        <span className="widget-handle inline-flex cursor-grab text-muted-foreground" aria-label="Drag to move" title="Drag to move">
          <GripVertical className="size-4" strokeWidth={1.75} />
        </span>
        <h3 className="min-w-0 flex-1 truncate text-[13px] font-semibold">{widget.title}</h3>
        <ScopeChip widget={widget} filter={applied} /> {/* the filter it actually applies */}
        <MenuRoot>
          <MenuTrigger asChild>
            <button
              type="button"
              aria-label={`Menu for ${widget.title}`}
              className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary focus-visible:outline-2 focus-visible:outline-ring"
            >
              <MoreHorizontal className="size-4" />
            </button>
          </MenuTrigger>
          <MenuContent>
            <SubMenu label="Change view" icon={<LayoutGrid />}>
              {compatibleViews(data).map((v) => (
                <MenuCheck key={v} checked={widget.spec.view.type === v} onSelect={() => changeView(v)}>
                  {VIEW_LABELS[v] ?? v}
                </MenuCheck>
              ))}
            </SubMenu>
            <MenuItem onSelect={() => actions.duplicate.mutate(widget.id, { onError: (e) => toast.error((e as Error).message) })}>
              <Copy /> Duplicate
            </MenuItem>
            <MenuItem onSelect={onToggleCollapse}>
              {collapsed ? <ChevronDown /> : <ChevronUp />} {collapsed ? "Expand" : "Collapse"}
            </MenuItem>
            <MenuCheck checked={asTable} onSelect={() => setAsTable((t) => !t)}>
              <span className="inline-flex items-center gap-2"><Table2 className="size-4 text-muted-foreground" /> Show as table</span>
            </MenuCheck>
            <MenuSeparator />
            <MenuItem destructive onSelect={remove}>
              <Trash2 /> Delete
            </MenuItem>
          </MenuContent>
        </MenuRoot>
      </header>
      {!collapsed && (
        <>
          <div className="relative h-0.5 shrink-0">
            {updating && <div className="absolute inset-y-0 left-0 w-1/2 animate-pulse bg-accent" aria-hidden />}
          </div>
          <div className={cn("min-h-0 flex-1 px-3 pb-1", updating && "opacity-60")} data-no-drag>
            {query.isLoading ? (
              <div className="h-full w-full animate-pulse rounded-lg bg-muted" aria-label="Loading" />
            ) : query.error ? (
              <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
                <p className="max-w-[90%] text-[13px] text-muted-foreground">{(query.error as Error).message}</p>
                <div className="flex gap-2">
                  <Button size="sm" onClick={() => query.refetch()}>Retry</Button>
                  <Button size="sm" variant="ghost" onClick={() => onExplain(widget)}>Show query</Button>
                </div>
              </div>
            ) : data ? (
              <WidgetChart spec={widget.spec} data={data} asTable={asTable} selected={selected} onSelect={onSelect} compact />
            ) : null}
          </div>
          <footer className="flex h-7 shrink-0 items-center gap-2 px-3 text-[12px] text-muted-foreground">
            <span className="font-mono">v{data?.version ?? version}</span>
            <span aria-hidden>·</span>
            <button type="button" className="text-accent hover:underline" onClick={() => onExplain(widget, data)}>
              How do you know?
            </button>
            {data?.truncated && <span className="ml-auto">first 2,000 rows</span>}
          </footer>
        </>
      )}
    </article>
  );
}

/** Two-way hover linking (PRD STORY-4): hovering a widget lights its card and the widgets related to
 * it; hovering a card lights its widget. A card click scrolls here and flashes the widget. */
function useLinking(widget: Widget) {
  const { hoveredWidget, setHoveredWidget, flashWidget, setFlashWidget, editLayout } = useUi();
  const cards = useCards(widget.dataset_id);
  const ref = useRef<HTMLElement>(null);
  const [flash, setFlash] = useState(false);
  useEffect(() => {
    if (flashWidget !== widget.id) return;
    ref.current?.scrollIntoView({ block: "center", behavior: "smooth" });
    setFlash(true);
    setFlashWidget(null);
    const t = setTimeout(() => setFlash(false), 1200);
    return () => clearTimeout(t);
  }, [flashWidget, widget.id, setFlashWidget]);
  const hoveredCard = hoveredWidget ? cards.data?.find((c) => c.widget_id === hoveredWidget) : undefined;
  const state = flash ? "flash" : hoveredWidget === widget.id ? "hovered"
    : hoveredCard?.related.some((r) => r.widget_id === widget.id) ? "related" : null;
  return {
    ref, state,
    enter: () => !editLayout && setHoveredWidget(widget.id), // suppressed while arranging
    leave: () => setHoveredWidget(null),
  };
}

function ScopeChip({ widget, filter }: { widget: Widget; filter: FilterClause | null }) {
  const rows = widget.spec.scope.rows;
  const parts = [rows.predicate ? "Some rows" : rows.selection_id ? "Selection" : "All rows"];
  if (filter) parts.push(`${filter.col} = ${String(filter.value)}`);
  return (
    <span className="hidden h-6 max-w-[40%] items-center truncate rounded-full border border-border bg-secondary px-2.5 text-[12px] text-muted-foreground @[360px]:inline-flex">
      {parts.join(" · ")}
    </span>
  );
}
