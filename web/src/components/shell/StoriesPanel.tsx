// The right panel (App Flow §2): story cards once the dashboard is built; placeholders until then.
export function StoriesPanel() {
  return (
    <section aria-labelledby="stories-title" className="flex h-full flex-col gap-3 overflow-y-auto p-4">
      <h2 id="stories-title" className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
        Stories
      </h2>
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-[120px] rounded-2xl border border-dashed border-border-strong" aria-hidden />
      ))}
      <p className="text-[13px] text-muted-foreground">Stories appear once the dashboard is built.</p>
    </section>
  );
}
