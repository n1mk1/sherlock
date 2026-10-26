// Answer blocks (App Flow §10.2, UI/UX brief §4.8): a number with its label, a table of up to 20 rows
// with "Open all n rows in CSV", a chart with Pin to dashboard, and text whose numbers are chips. Web
// answers (TRD §8.2 web_context) are set apart: text with numbered citations, then "Searched the web for"
// and the sources, each excerpt quoted as the page has it.
import { Pin } from "lucide-react";
import { lazy, Suspense } from "react";
import { Link } from "react-router-dom";
import type { AnswerBlock, AnswerBody, AnswerRun, WebResult } from "@/api/types";
import { ResultTable } from "@/components/charts/ResultTable";
import { Button } from "@/components/ui/button";

// The chart libraries load with the first chart answer, not with the page.
const WidgetChart = lazy(() => import("@/components/charts/adapter").then((m) => ({ default: m.WidgetChart })));

export function RunsView({ body }: { body: AnswerBody }) {
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

function splitLines(runs: AnswerRun[]): AnswerRun[][] {
  const out: AnswerRun[][] = [[]];
  for (const r of runs) {
    if (r.type === "text" && r.text === "\n") out.push([]);
    else out[out.length - 1].push(r);
  }
  return out.filter((l) => l.length);
}

/** A number chip (UI/UX brief §4.6): mono, --info-soft fill; its value was filled in by code. */
export function RunView({ run }: { run: AnswerRun }) {
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
  if (run.type === "cite") {
    return (
      <a href={run.url} target="_blank" rel="noopener noreferrer" title={run.title}
        className="ml-0.5 align-super text-[10.5px] font-medium text-accent hover:underline">[{run.n}]</a>
    );
  }
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
          <div className="h-[220px] overflow-hidden rounded-lg border border-border bg-card p-2">
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
    case "web_sources":
      return <WebSources query={block.query} results={block.results} cached={block.cached} />;
    case "text":
      if (block.labeled === "web") {
        return (
          <div className="rounded-lg border border-dashed border-info/50 px-3 py-2 text-[13px] text-foreground-2"
            title="From the web pages cited below, not computed from your data">
            <RunsView body={block.body} />
          </div>
        );
      }
      // General knowledge (ask_meaning) is set apart from what the data says.
      return block.labeled === "general" ? (
        <div className="rounded-lg border border-dashed border-border px-3 py-2 text-[13px] text-foreground-2" title="From the model's general knowledge, not computed from your data">
          <RunsView body={block.body} />
        </div>
      ) : (
        <div className="text-[14px]"><RunsView body={block.body} /></div>
      );
  }
}

/** "Searched the web for: …" and the results, collapsed: each one's title (a link), site, retrieval date and its
 * excerpt in quotes, exactly as the page has it. Numbers from the web appear only here, never as chips. */
function WebSources({ query, results, cached }: { query: string; results: WebResult[]; cached: boolean }) {
  return (
    <div className="flex flex-col gap-1 text-[12.5px]">
      <span className="text-muted-foreground">
        Searched the web for: <span className="text-foreground-2">“{query}”</span>{cached ? " (from earlier today)" : ""}
      </span>
      {results.length > 0 && (
        <details>
          <summary className="cursor-pointer text-accent hover:underline">
            {results.length === 1 ? "1 source" : `${results.length} sources`}
          </summary>
          <ol className="mt-1.5 flex flex-col gap-2">
            {results.map((r) => (
              <li key={r.n} className="flex flex-col gap-0.5">
                <span>
                  [{r.n}]{" "}
                  <a href={r.url} target="_blank" rel="noopener noreferrer" className="font-medium text-accent hover:underline">{r.title}</a>
                  <span className="text-muted-foreground"> · {r.domain} · retrieved {r.retrieved_at}</span>
                </span>
                <q className="border-l-2 border-border pl-2 italic text-foreground-2">{r.snippet}</q>
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  );
}
