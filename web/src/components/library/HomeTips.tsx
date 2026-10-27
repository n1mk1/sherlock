// The right panel on `/` (App Flow §2): what Sherlock does with a CSV, before one is open.
const TIPS: [string, string][] = [
  ["Clean", "Sherlock checks every column and drafts a cleaning plan. Nothing changes until you start it; every fix is a step you can undo, and rows it can't fix are quarantined, never deleted."],
  ["Look", "The grid shows the data with each fix marked. Edit cells, add or delete rows, then save a new version."],
  ["Ask", "Ask for a number, the rows where something holds, a chart, or what drives a column. Every number opens the query behind it."],
  ["Export", "The whole analysis exports as a runnable Jupyter notebook."],
];

export function HomeTips() {
  return (
    <section aria-labelledby="tips-title" className="flex h-full flex-col gap-3 overflow-y-auto p-4">
      <h2 id="tips-title" className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">How it works</h2>
      <ol className="flex flex-col gap-3 text-[13px]">
        {TIPS.map(([title, text]) => (
          <li key={title} className="rounded-2xl border border-border bg-card p-3">
            <span className="font-medium">{title}.</span> <span className="text-muted-foreground">{text}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}
