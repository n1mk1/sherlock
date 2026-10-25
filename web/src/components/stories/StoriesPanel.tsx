// The stories panel (the right panel outside the CSV tab, App Flow §2, §7.4): the overview card, then a
// card per widget in dashboard order; placeholders while the stories job writes them. A chip opens
// the evidence drawer: the fact behind the number and the query or formula it came from.
import { useMatch } from "react-router-dom";
import { useState } from "react";
import { useWidgets } from "@/api/queries";
import { useCards, useEvidence } from "@/api/stories";
import type { Card } from "@/api/types";
import { Drawer } from "@/components/ui/drawer";
import { StoryCard } from "./StoryCard";

export function StoriesPanel() {
  const match = useMatch("/d/:datasetId/:tab");
  const datasetId = match?.params.datasetId;
  const cards = useCards(datasetId);
  const widgets = useWidgets(datasetId ?? "");
  const [evidence, setEvidence] = useState<{ card: Card; chip: string } | null>(null);
  const titles = Object.fromEntries((widgets.data?.widgets ?? []).map((w) => [w.id, w.title]));
  const list = cards.data ?? [];
  return (
    <section aria-labelledby="stories-title" className="flex h-full flex-col gap-3 overflow-y-auto p-4">
      <h2 id="stories-title" className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Stories</h2>
      {list.length === 0 && (
        <>
          {[0, 1, 2].map((i) => <div key={i} className="h-[120px] rounded-2xl border border-dashed border-border-strong" aria-hidden />)}
          <p className="text-[13px] text-muted-foreground">
            {datasetId && widgets.data?.widgets.length ? "Writing the stories…" : "Stories appear once the dashboard is built."}
          </p>
        </>
      )}
      {list.map((c) => (
        <StoryCard key={c.id} card={c}
          title={c.widget_id ? titles[c.widget_id] ?? "" : c.kind === "synthesis" ? "Synthesis" : c.kind === "answer" ? "Answer" : "Overview"}
          onEvidence={(card, chip) => setEvidence({ card, chip })} />
      ))}
      <EvidenceDrawer value={evidence} onClose={() => setEvidence(null)} />
    </section>
  );
}

export function EvidenceDrawer({ value, onClose }: { value: { card: Card; chip: string } | null; onClose: () => void }) {
  const { data, error } = useEvidence(value?.card.id ?? null, value?.chip ?? null);
  return (
    <Drawer open={!!value} onOpenChange={(o) => !o && onClose()} title="How do you know?">
      {error ? <p className="text-muted-foreground">{(error as Error).message}</p> : !data ? <p className="text-muted-foreground">Loading…</p> : (
        <div className="flex flex-col gap-3 text-[14px]">
          {data.unverified ? (
            <p><span className="font-mono">{String(data.value)}</span> was typed by hand, not computed, so it has no evidence.</p>
          ) : (
            <>
              <p><span className="font-mono">{data.formatted}</span> is the {data.label}, computed on version <span className="font-mono">{data.version}</span>.</p>
              {data.sql && (
                <>
                  <pre className="overflow-x-auto whitespace-pre-wrap rounded-md bg-muted p-3 font-mono text-[12px]">{data.sql}</pre>
                  <button type="button" className="self-start text-[13px] text-accent hover:underline"
                    onClick={() => navigator.clipboard?.writeText(data.sql ?? "")}>Copy</button>
                </>
              )}
              {data.formula && <p className="text-muted-foreground">How: {data.formula}{data.from?.length ? ` (from ${data.from.join(", ")})` : ""}.</p>}
              {data.method && <p className="text-muted-foreground">Test: {data.method}.</p>}
            </>
          )}
        </div>
      )}
    </Drawer>
  );
}
