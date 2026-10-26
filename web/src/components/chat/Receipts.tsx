// "How I worked it out" (App Flow §10.2, §5; UI/UX §4.8): the receipt of an answer or a clean, read from
// `llm_calls` (TRD §4.9, §4.10). Each step shows the model that ran it, how long it took, its tokens and
// whether it was a repair or Ultra standing in for Super (TRD §3.5), then the total. Collapsed at first;
// the calls are fetched when it opens.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { request } from "@/api/client";
import type { components } from "@/api/schema";
import { cn } from "@/lib/utils";

export type Receipt = components["schemas"]["Receipt"];
export type ModelCall = components["schemas"]["ModelCall"];

// What each call purpose did, in plain words (UI/UX §7). An unknown purpose shows as itself.
const DID: Record<string, string> = {
  route: "Read the question", plan: "Planned the steps", sql: "Wrote the query", predicate: "Wrote the row filter",
  widget: "Designed the widget", update_widget: "Changed the widget", compose: "Wrote the answer",
  stats: "Chose the test", meaning: "Explained the column", edits: "Drafted the edits", ask_story: "Read the cards",
  plan_edits: "Changed the cleaning plan", summary: "Summarized the thread",
  diagnose: "Diagnosed an issue", propose: "Proposed fixes", critic: "Reviewed a fix", curate: "Chose the widgets",
  narrate: "Wrote a story", overview: "Wrote the overview", synthesis: "Made sense of the cards",
};
// A web request (`role: "web"`) is named by its tool.
const WEB: Record<string, string> = { "tavily-search": "Searched the web", "tavily-extract": "Read a web page", "tavily-map": "Mapped a website" };

export function stepName(call: ModelCall): string {
  if (call.role === "web") return WEB[call.model] ?? "Asked the web";
  return DID[call.purpose] ?? call.purpose;
}

export function seconds(ms: number): string {
  return ms < 100 ? "under 0.1 s" : `${(ms / 1000).toFixed(1)} s`;
}

const plural = (n: number, one: string, many = `${one}s`) => `${n.toLocaleString()} ${n === 1 ? one : many}`;

export function totalLine(t: Receipt["total"]): string {
  const parts = [plural(t.calls, "call"), `${seconds(t.latency_ms)} waiting on them`, plural(t.tokens, "token")];
  if (t.repaired) parts.push(plural(t.repaired, "repair"));
  if (t.failed) parts.push(plural(t.failed, "failed attempt"));
  if (t.cached) parts.push(`${t.cached.toLocaleString()} from the cache`);
  return parts.join(" · ");
}

export function Receipts({ path, className }: { path: string; className?: string }) {
  const [open, setOpen] = useState(false);
  const { data, isPending, isError } = useQuery({
    queryKey: ["calls", path],
    enabled: open,
    staleTime: 30_000,
    queryFn: () => request<Receipt>("GET", path),
  });
  return (
    <details open={open} className={cn("text-[13px]", className)}>
      <summary
        className="cursor-pointer text-accent hover:underline"
        onClick={(e) => { e.preventDefault(); setOpen((o) => !o); }}
      >
        How I worked it out
      </summary>
      {open && (
        <div className="mt-2 flex flex-col gap-2">
          {isPending && <p className="text-muted-foreground">Reading the calls…</p>}
          {isError && <p className="text-muted-foreground">The calls couldn't be read. Try again in a minute.</p>}
          {data && !data.calls.length && <p className="text-muted-foreground">No model was called for this.</p>}
          {data && data.calls.length > 0 && (
            <>
              <table className="w-full text-left text-[12px]">
                <thead className="text-muted-foreground">
                  <tr>
                    <th className="font-normal">Step</th><th className="font-normal">Model</th>
                    <th className="text-right font-normal">Time</th><th className="text-right font-normal">Tokens</th>
                  </tr>
                </thead>
                <tbody>
                  {data.calls.map((c, i) => (
                    <tr key={c.id} className={cn("align-top", !c.ok && "text-muted-foreground")}>
                      <td className="pr-2">
                        {i + 1}. {stepName(c)}
                        {c.repaired && <span className="ml-1 text-accent">(repair)</span>}
                        {c.fallback_from && <span className="ml-1 text-accent">(in place of the {c.fallback_from} model)</span>}
                        {!c.ok && <span className="ml-1 text-warning">{c.error?.includes("cut off") ? "(cut off, asked again)" : "(failed)"}</span>}
                      </td>
                      <td className="break-all pr-2 font-mono">{c.model}</td>
                      <td className="whitespace-nowrap text-right font-mono">{c.cached ? "cached" : c.latency_ms == null ? "" : seconds(c.latency_ms)}</td>
                      <td className="text-right font-mono">{c.tokens ? c.tokens.toLocaleString() : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {data.total.calls > data.calls.length && (
                <p className="text-muted-foreground">and {plural(data.total.calls - data.calls.length, "more call")}</p>
              )}
              <p className="font-medium">Total: {totalLine(data.total)}</p>
            </>
          )}
        </div>
      )}
    </details>
  );
}
