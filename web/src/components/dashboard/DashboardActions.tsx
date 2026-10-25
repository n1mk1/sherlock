// The dashboard's part of the context row (UI/UX brief §5.5): the global filter chip, then Add widget
// and the Edit layout toggle.
import { LayoutDashboard, Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useFilters, useGlobalFilter } from "@/state/filters";
import { useUi } from "@/state/ui";

export function FilterChip({ datasetId }: { datasetId: string }) {
  const filter = useGlobalFilter(datasetId);
  const clear = useFilters((s) => s.clear);
  if (!filter) return null;
  return (
    <span className="inline-flex h-7 items-center gap-1 rounded-full border border-border bg-secondary pl-2.5 pr-1 text-[13px]">
      <span className="font-medium">{filter.col}</span> = <span className="font-mono">{String(filter.value)}</span>
      <button
        type="button"
        aria-label="Clear the filter"
        onClick={() => clear(datasetId)}
        className="inline-flex size-5 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground"
      >
        <X className="size-3.5" />
      </button>
    </span>
  );
}

export function DashboardActions() {
  const { editLayout, setEditLayout, setAddWidgetOpen } = useUi();
  return (
    <>
      <Button size="sm" onClick={() => setAddWidgetOpen(true)}>
        <Plus /> Add widget
      </Button>
      <Button
        size="sm"
        variant="ghost"
        aria-pressed={editLayout}
        className={cn(editLayout && "bg-secondary")}
        onClick={() => setEditLayout(!editLayout)}
      >
        <LayoutDashboard /> Edit layout
      </Button>
    </>
  );
}
