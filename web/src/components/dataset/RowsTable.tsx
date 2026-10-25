// A read-only, paged view of the current version from the rows API (TRD §4.3). The editable Glide
// grid replaces it in the CSV tab (Implementation Plan D5.1); marks already show here.
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { request } from "@/api/client";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface RowsPage {
  version: number;
  total: number;
  columns: { name: string; type: string }[];
  rows: { _row_id: number; cells: Record<string, unknown>; marks: Record<string, string>; quarantined: boolean }[];
}

const PAGE = 100;
const NUMERIC = /^(BIGINT|INTEGER|DOUBLE|FLOAT|DECIMAL|SMALLINT|TINYINT|HUGEINT|REAL)/;

export function RowsTable({ datasetId, version }: { datasetId: string; version: number }) {
  const [offset, setOffset] = useState(0);
  // ?rows=<selection id> shows a saved selection, e.g. "open these rows" from chat (App Flow §1).
  const [params, setParams] = useSearchParams();
  const selection = params.get("rows");
  const { data, isLoading, error } = useQuery({
    queryKey: ["rows", datasetId, version, offset, selection],
    queryFn: () =>
      request<RowsPage>("GET", `/api/v1/datasets/${datasetId}/rows?offset=${offset}&limit=${PAGE}&version=${version}${selection ? `&selection=${selection}` : ""}`),
    placeholderData: (prev) => prev,
  });
  if (error) return <p className="p-6 text-destructive">{(error as Error).message}</p>;
  if (isLoading || !data) return <p className="p-6 text-muted-foreground">Loading rows…</p>;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {selection && (
        <div className="flex items-center gap-2 border-b border-border px-4 py-2 text-[13px]">
          <span className="inline-flex h-7 items-center rounded-full border border-accent bg-accent-soft px-2.5">
            {data.total.toLocaleString()} rows selected
          </span>
          <Button size="sm" variant="ghost" onClick={() => { setParams({}); setOffset(0); }}>Show all rows</Button>
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="border-collapse text-[13px]">
          <thead className="sticky top-0 bg-background">
            <tr>
              <th className="border-b border-r border-border px-2 py-1.5 text-right font-mono text-[12px] text-muted-foreground">#</th>
              {data.columns.map((c) => (
                <th key={c.name} className="whitespace-nowrap border-b border-border px-3 py-1.5 text-left font-semibold">
                  {c.name}
                  <span className="ml-1.5 font-mono text-[11px] font-normal text-muted-foreground">{c.type.toLowerCase()}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => (
              <tr key={r._row_id} className={cn(r.quarantined && "opacity-60")} title={r.quarantined ? "Quarantined: left out of charts, models and stories" : undefined}>
                <td className={cn("border-b border-r border-border bg-muted px-2 py-1 text-right font-mono text-[12px] text-muted-foreground", r.quarantined && "line-through")}>{r._row_id}</td>
                {data.columns.map((c) => {
                  const mark = r.marks[c.name];
                  const v = r.cells[c.name];
                  return (
                    <td
                      key={c.name}
                      title={mark ? `${mark} by a step` : undefined}
                      className={cn(
                        "max-w-[260px] truncate whitespace-nowrap border-b border-border px-3 py-1",
                        NUMERIC.test(c.type) && "text-right font-mono text-[12.5px]",
                        // UI brief §4.7: never color alone; changed has a top marker, flagged a dashed outline.
                        mark === "changed" && "bg-changed shadow-[inset_0_4px_0_-2px_var(--info)]",
                        mark === "flagged" && "outline outline-1 -outline-offset-2 outline-dashed outline-warning",
                        mark === "invalid" && "underline decoration-destructive decoration-1 underline-offset-4",
                      )}
                    >
                      {v === null || v === undefined ? <span className="text-muted-foreground">·</span> : String(v)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex items-center gap-2 border-t border-border px-4 py-2 text-[12px] text-muted-foreground">
        <span>
          Rows {Math.min(offset + 1, data.total).toLocaleString()}–{Math.min(offset + PAGE, data.total).toLocaleString()} of{" "}
          {data.total.toLocaleString()}
        </span>
        <Button size="icon" variant="ghost" aria-label="Previous rows" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
          <ChevronLeft />
        </Button>
        <Button size="icon" variant="ghost" aria-label="Next rows" disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>
          <ChevronRight />
        </Button>
      </div>
    </div>
  );
}
