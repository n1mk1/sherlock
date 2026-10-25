// A read-only, paged view of the current version from the rows API (TRD §4.3). The editable Glide
// grid replaces it in the CSV tab (Implementation Plan D5.1); marks already show here.
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
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
  const { data, isLoading, error } = useQuery({
    queryKey: ["rows", datasetId, version, offset],
    queryFn: () => request<RowsPage>("GET", `/api/v1/datasets/${datasetId}/rows?offset=${offset}&limit=${PAGE}&version=${version}`),
    placeholderData: (prev) => prev,
  });
  if (error) return <p className="p-6 text-destructive">{(error as Error).message}</p>;
  if (isLoading || !data) return <p className="p-6 text-muted-foreground">Loading rows…</p>;
  return (
    <div className="flex min-h-0 flex-1 flex-col">
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
              <tr key={r._row_id} className={cn(r.quarantined && "text-muted-foreground line-through decoration-warning/60")}>
                <td className="border-b border-r border-border px-2 py-1 text-right font-mono text-[12px] text-muted-foreground">{r._row_id}</td>
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
                        mark === "changed" && "bg-changed",
                        mark === "flagged" && "bg-warning/10",
                        mark === "invalid" && "outline outline-1 -outline-offset-1 outline-destructive/60",
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
