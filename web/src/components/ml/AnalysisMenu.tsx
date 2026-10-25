// The analysis dropdown (PRD ML-1, App Flow §9 step 1, UI/UX brief §5.8): options grouped Explain ·
// Predict · Group · Unusual · Time · Plain chart; an option that doesn't fit the data is disabled with
// its reason. With cuts 4 and 7 only "What drives this?" runs.
import { FlaskConical } from "lucide-react";
import { toast } from "sonner";
import { useRecipes, type Recipe } from "@/api/ml";
import { useWidgetActions } from "@/api/queries";
import type { Widget } from "@/api/types";
import { MenuCheck, MenuContent, MenuItem, MenuLabel, MenuRoot, MenuSeparator, MenuTrigger } from "@/components/ui/menu";

const GROUPS: [Recipe["group"], string][] = [
  ["explain", "Explain"], ["predict", "Predict"], ["group", "Group"], ["unusual", "Unusual"], ["time", "Time"],
];

export function AnalysisMenu({ widget, onChoose }: { widget: Widget; onChoose: (recipe: string) => void }) {
  const recipes = useRecipes(widget.dataset_id);
  const actions = useWidgetActions(widget.dataset_id);
  const isMl = widget.spec.op.type === "ml";
  // Undo swaps back to the chart this analysis replaced (an analysis made by the builder has none).
  const backToChart = () =>
    actions.undo.mutate(widget.id, {
      onError: (e) => toast.error((e as { status?: number }).status === 409
        ? "This analysis wasn't made from a chart, so there's no chart to go back to." : (e as Error).message),
    });
  return (
    <MenuRoot>
      <MenuTrigger asChild>
        <button
          type="button"
          aria-label={`Analyze ${widget.title}`}
          title="Analyze"
          className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary focus-visible:outline-2 focus-visible:outline-ring"
        >
          <FlaskConical className="size-4" strokeWidth={1.75} />
        </button>
      </MenuTrigger>
      <MenuContent>
        {GROUPS.map(([group, label]) => {
          const items = (recipes.data ?? []).filter((r) => r.group === group);
          if (!items.length) return null;
          return (
            <div key={group} role="group" aria-label={label}>
              <MenuLabel>{label}</MenuLabel>
              {items.map((r) => (
                <MenuItem key={r.id} disabled={!r.compatible} onSelect={() => onChoose(r.id)} className="h-auto min-h-8 py-1">
                  <span className="flex min-w-0 flex-col leading-tight" title={r.reason}>
                    <span>{r.label}</span>
                    {!r.compatible && r.reason && <span className="truncate text-[11px] text-muted-foreground">{r.reason}</span>}
                  </span>
                </MenuItem>
              ))}
            </div>
          );
        })}
        {recipes.isLoading && <p className="px-2 py-1.5 text-muted-foreground">Checking what fits…</p>}
        <MenuSeparator />
        <MenuCheck checked={!isMl} onSelect={() => isMl && backToChart()}>
          Plain chart (SQL)
        </MenuCheck>
      </MenuContent>
    </MenuRoot>
  );
}
