// Add widget (App Flow §7.3): "Describe it" (the chat agent's create_widget, POST /widgets {prompt})
// and quick templates by column: bar of X by Y, KPI of X, a table of columns.
import { useState } from "react";
import { toast } from "sonner";
import { useDatacard, useWidgetActions } from "@/api/queries";
import type { ColumnCard, WidgetSpec } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Drawer } from "@/components/ui/drawer";
import { Segmented } from "@/components/ui/segmented";
import { useUi } from "@/state/ui";

const q = (name: string) => `"${name.replace(/"/g, '""')}"`;
type Template = "bar" | "kpi" | "table";

export function templateSpec(kind: Template, x: string, y: string, cols: string[]): { title: string; spec: WidgetSpec } {
  const scope = { columns: { x: kind === "bar" ? x : null, y: y || null }, rows: { inherit_global_filters: true } };
  if (kind === "bar") {
    const value = y ? `AVG(${q(y)}) AS ${q(`avg_${y}`)}` : "COUNT(*) AS n";
    return {
      title: y ? `Average ${y} by ${x}` : `Rows by ${x}`,
      spec: {
        scope, view: { type: "bar", options: { x, y: y ? `avg_${y}` : "n" } },
        op: { type: "sql", sql: `SELECT ${q(x)}, ${value} FROM t WHERE {{rows}} AND ${q(x)} IS NOT NULL GROUP BY 1 ORDER BY 1` },
      },
    };
  }
  if (kind === "kpi") {
    const value = y ? `AVG(${q(y)}) AS value, COUNT(${q(y)}) AS n` : "COUNT(*) AS value";
    return {
      title: y ? `Average ${y}` : "Rows",
      spec: { scope, view: { type: "kpi", options: { value: "value", ...(y ? { sub: "n" } : {}) } },
        op: { type: "sql", sql: `SELECT ${value} FROM t WHERE {{rows}}` } },
    };
  }
  const list = cols.length ? cols.map(q).join(", ") : "*";
  return {
    title: "Rows",
    spec: { scope, view: { type: "table", options: {} }, op: { type: "sql", sql: `SELECT ${list} FROM t WHERE {{rows}} LIMIT 50` } },
  };
}

export function AddWidgetDrawer({ datasetId }: { datasetId: string }) {
  const { addWidgetOpen, setAddWidgetOpen } = useUi();
  const card = useDatacard(datasetId, addWidgetOpen);
  const { create } = useWidgetActions(datasetId);
  const [prompt, setPrompt] = useState("");
  const [kind, setKind] = useState<Template>("bar");
  const [x, setX] = useState("");
  const [y, setY] = useState("");
  const columns = (card.data?.columns ?? []).filter((c) => c.role !== "empty");
  const dims = columns.filter((c) => (c.role === "dimension" || c.role === "target_like") && c.distinct <= 50);
  const measures = columns.filter((c) => c.role === "measure" || ["int", "float", "bool"].includes(c.type));

  const done = (out: { widget: { title: string }; warning?: string }) => {
    setAddWidgetOpen(false);
    setPrompt("");
    toast(`Added “${out.widget.title}”`);
    if (out.warning) toast.warning(out.warning);
  };
  const fail = (e: unknown) => toast.error((e as Error).message);

  return (
    <Drawer open={addWidgetOpen} onOpenChange={setAddWidgetOpen} title="Add widget">
      <div className="flex flex-col gap-6">
        <section className="flex flex-col gap-2">
          <h3 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Describe it</h3>
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            rows={3}
            placeholder="A bar chart of average fare by port"
            className="w-full resize-none rounded-lg border border-input bg-card p-3 text-[14px] outline-none focus-visible:border-accent"
          />
          <Button
            variant="primary"
            className="self-start"
            disabled={!prompt.trim()}
            loading={create.isPending && !!prompt}
            onClick={() => create.mutate({ prompt: prompt.trim() }, { onSuccess: done, onError: fail })}
          >
            Add
          </Button>
        </section>
        <section className="flex flex-col gap-3">
          <h3 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Quick templates</h3>
          <Segmented
            label="Template"
            value={kind}
            onChange={(v) => setKind(v)}
            options={[{ value: "bar", label: "Bar of X by Y" }, { value: "kpi", label: "KPI of X" }, { value: "table", label: "Table" }]}
          />
          {kind === "bar" && <Pick label="Categories (X)" value={x} onChange={setX} columns={dims} />}
          {kind !== "table" && <Pick label="Value (Y), averaged" value={y} onChange={setY} columns={measures} empty="Row count" />}
          <Button
            className="self-start"
            disabled={kind === "bar" && !x}
            onClick={() => {
              const { title, spec } = templateSpec(kind, x, y, columns.slice(0, 12).map((c) => c.name));
              create.mutate({ ...spec, title }, { onSuccess: done, onError: fail });
            }}
          >
            Add template
          </Button>
        </section>
      </div>
    </Drawer>
  );
}

function Pick({ label, value, onChange, columns, empty }: {
  label: string; value: string; onChange: (v: string) => void; columns: ColumnCard[]; empty?: string;
}) {
  return (
    <label className="flex flex-col gap-1 text-[13px]">
      <span className="text-muted-foreground">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-9 rounded-md border border-input bg-card px-2 text-[14px] outline-none focus-visible:border-accent"
      >
        <option value="">{empty ?? "Choose a column"}</option>
        {columns.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
      </select>
    </label>
  );
}
