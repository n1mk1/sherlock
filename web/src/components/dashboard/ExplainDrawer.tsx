// "How do you know?" (PRD DASH-7, App Flow §7.3): the SQL exactly as it runs now, with Copy and the
// row count. An analysis widget shows its run's reproduction code instead (TRD §6.7), the same code the
// exported notebook runs.
import { Check, Copy } from "lucide-react";
import { useState } from "react";
import { useRunCode } from "@/api/ml";
import { filterParam, useExplain } from "@/api/queries";
import type { Widget, WidgetData } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Drawer } from "@/components/ui/drawer";
import { appliedFilter, useGlobalFilter } from "@/state/filters";

export function ExplainDrawer({ widget, data, onClose }: { widget: Widget | null; data?: WidgetData; onClose: () => void }) {
  const filter = useGlobalFilter(widget?.dataset_id ?? "");
  const explain = useExplain(widget, filterParam(widget ? appliedFilter(widget, filter) : null));
  const isMl = widget?.spec.op.type === "ml";
  const code = useRunCode(isMl ? widget?.run_id ?? null : null, isMl);
  const [copied, setCopied] = useState(false);
  const sql = isMl ? code.data?.python : explain.data?.sql;
  return (
    <Drawer open={!!widget} onOpenChange={(o) => !o && onClose()} title="How do you know?">
      {widget && (
        <div className="flex flex-col gap-4">
          {isMl ? (
            <p className="text-[13px] text-muted-foreground">
              <span className="font-medium text-foreground">{widget.title}</span> is an analysis. Its numbers come from this code,
              run on the same rows, features, folds and seed; the exported notebook runs it too. Quarantined rows are left out.
            </p>
          ) : (
            <p className="text-[13px] text-muted-foreground">
              <span className="font-medium text-foreground">{widget.title}</span> runs this query on version{" "}
              <span className="font-mono">v{explain.data?.version ?? data?.version}</span>. Quarantined rows are left out.
            </p>
          )}
          {(isMl ? code.error : explain.error) ? (
            <p className="text-[13px] text-destructive">{((isMl ? code.error : explain.error) as Error).message}</p>
          ) : (
            <pre className="max-h-[50vh] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-muted p-3 font-mono text-[12px] leading-relaxed">
              {sql ?? "…"}
            </pre>
          )}
          <div className="flex items-center gap-3">
            <Button
              size="sm"
              disabled={!sql}
              onClick={() => {
                if (!sql) return;
                navigator.clipboard?.writeText(sql);
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              }}
            >
              {copied ? <Check /> : <Copy />} {copied ? "Copied" : "Copy"}
            </Button>
            {data && !isMl && (
              <span className="text-[13px] text-muted-foreground">
                <span className="font-mono">{data.row_count.toLocaleString("en-US")}</span> result {data.row_count === 1 ? "row" : "rows"}
                {data.truncated && " (capped at 2,000)"}
              </span>
            )}
          </div>
        </div>
      )}
    </Drawer>
  );
}
