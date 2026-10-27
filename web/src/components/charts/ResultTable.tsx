// A result as a table (the "table" view, chat table answers). Kept apart from the
// chart adapter so pages that only show tables don't load the chart libraries.
import type { Highlight, ChartData } from "@/api/types";
import { formatCell, formatPeriod, isPctColumn } from "@/lib/format";
import { cn } from "@/lib/utils";

export function ResultTable({ data, highlight, compact, limit }: { data: ChartData | { columns: ChartData["columns"]; rows: unknown[][] }; highlight?: Highlight; compact?: boolean; limit?: number }) {
  const pct = data.columns.map((c, i) => isPctColumn(c.name, data.rows.map((r) => r[i])));
  const rows = limit ? data.rows.slice(0, limit) : data.rows;
  return (
    <div className="h-full overflow-auto">
      <table className={cn("w-full border-collapse text-[13px]", compact && "text-[12px]")}>
        <thead className="sticky top-0 bg-card">
          <tr>
            {data.columns.map((c) => (
              <th key={c.name} className="border-b border-border px-2 py-1.5 text-left font-semibold">{c.name}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={cn(highlight && String(r[0]) === highlight.key && "bg-accent-soft")}>
              {r.map((v, j) => (
                <td key={j} className={cn("border-b border-border px-2 py-1", typeof v === "number" && "text-right font-mono")}>
                  {data.columns[j]?.type === "DATE" ? formatPeriod(v) : formatCell(v, pct[j])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
