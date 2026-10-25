// Answer blocks (App Flow §10.2, UI/UX brief §4.8): a number with its label, a table of up to 20 rows
// with "Open all n rows in CSV", a chart with Pin to dashboard, and text whose numbers are chips.
import { Pin } from "lucide-react";
import { lazy, Suspense } from "react";
import { Link } from "react-router-dom";
import type { AnswerBlock, CardBody, Run } from "@/api/types";
import { ResultTable } from "@/components/charts/ResultTable";
import { Button } from "@/components/ui/button";

// The chart libraries load with the first chart answer, not with the page.
const WidgetChart = lazy(() => import("@/components/charts/adapter").then((m) => ({ default: m.WidgetChart })));

export function RunsView({ body }: { body: CardBody }) {
  return (
    <>
      {body.blocks.map((b, i) =>
        b.type === "bullets" ? (
          <ul key={i} className="flex list-disc flex-col gap-1 pl-5">
            {splitLines(b.runs).map((line, j) => <li key={j}>{line.map((r, k) => <RunView key={k} run={r} />)}</li>)}
          </ul>
        ) : (
          <p key={i} className="leading-relaxed">{b.runs.map((r, k) => <RunView key={k} run={r} />)}</p>
        ),
      )}
    </>
  );
}

function splitLines(runs: Run[]): Run[][] {
  const out: Run[][] = [[]];
  for (const r of runs) {
    if (r.type === "text" && r.text === "\n") out.push([]);
    else out[out.length - 1].push(r);
  }
  return out.filter((l) => l.length);
}

/** A number chip (UI/UX brief §4.6): mono, --info-soft fill; its value was filled in by code. */
export function RunView({ run }: { run: Run }) {
  if (run.type === "chip") {
    return (
      <span
        title={run.unverified ? "Typed by you, not computed" : "Computed from the query below"}
        className="mx-0.5 inline-flex items-center rounded-[6px] border border-info/35 bg-info-soft px-[5px] font-mono text-[12.5px] text-foreground"
      >
        {run.value}
      </span>
    );
  }
  if (run.type === "label") return <span className="font-medium">{run.text ?? run.ref}</span>;
  return <>{run.text}</>;
}

export function BlockView({ block, datasetId, onPin, pinning }: {
  block: AnswerBlock; datasetId: string; onPin?: () => void; pinning?: boolean;
}) {
  switch (block.type) {
    case "number":
      return (
        <div className="flex flex-col gap-0.5">
          <span className="font-mono text-[26px] font-medium leading-tight">{block.formatted}</span>
          <span className="text-[12px] text-muted-foreground">{block.label}</span>
        </div>
      );
    case "table":
      return (
        <div className="flex flex-col gap-1.5">
          <div className="max-h-[260px] overflow-hidden rounded-lg border border-border">
            <ResultTable data={block} compact limit={20} />
          </div>
          {block.selection_id ? (
            <Link to={`/d/${datasetId}/csv?rows=${block.selection_id}`} className="text-[13px] text-accent hover:underline">
              Open {block.total > 20 ? `all ${block.total.toLocaleString("en-US")}` : "these"} rows in CSV
            </Link>
          ) : block.total > block.rows.length ? (
            <span className="text-[12px] text-muted-foreground">Showing {block.rows.length} of {block.total.toLocaleString("en-US")} rows</span>
          ) : null}
        </div>
      );
    case "chart":
      return (
        <div className="flex flex-col gap-1.5">
          <div className="h-[220px] rounded-lg border border-border bg-card p-2">
            <Suspense fallback={<div className="h-full w-full animate-pulse rounded bg-muted" />}>
              <WidgetChart spec={block.spec} data={block.data} compact />
            </Suspense>
          </div>
          {block.widget_id ? (
            <Link to={`/d/${datasetId}/dashboard?widget=${block.widget_id}`} className="text-[13px] text-accent hover:underline">
              Open the widget
            </Link>
          ) : onPin ? (
            <Button size="sm" className="self-start" loading={pinning} onClick={onPin}><Pin /> Pin to dashboard</Button>
          ) : null}
        </div>
      );
    case "text":
      return <div className="text-[14px]"><RunsView body={block.body} /></div>;
  }
}
