// The right panel on `/` (App Flow §2): what Sherlock does with a CSV, before one is open. Each step
// carries the hue its part of the app uses.
import { BookOpen, MessageCircle, Sparkles, Table2 } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

const TIPS: [string, string, ReactNode, string][] = [
  ["Clean", "Sherlock finds problems and drafts the fixes. Nothing changes until you start, and every step can be undone.",
    <Sparkles />, "bg-violet-soft text-violet"],
  ["Review", "Every fix is marked in the grid. Edit cells and rows yourself, too.", <Table2 />, "bg-teal-soft text-teal"],
  ["Ask", "Ask in plain words for a number, rows, or a chart. Every answer shows its source.", <MessageCircle />, "bg-blue-soft text-blue"],
  ["Export", "Take the whole analysis with you as a Jupyter notebook.", <BookOpen />, "bg-amber-soft text-amber"],
];

export function HomeTips() {
  return (
    <section aria-labelledby="tips-title" className="flex h-full flex-col gap-6 px-6 py-5">
      <h2 id="tips-title" className="type-label">How it works</h2>
      <ol className="flex flex-col gap-6">
        {TIPS.map(([title, text, icon, tint]) => (
          <li key={title} className="flex gap-3.5">
            <span className={cn("inline-flex size-8 shrink-0 items-center justify-center rounded-full [&_svg]:size-4", tint)} aria-hidden>
              {icon}
            </span>
            <div className="flex flex-col gap-0.5">
              <span className="type-heading text-[14px]">{title}</span>
              <span className="text-[13px] leading-snug text-muted-foreground">{text}</span>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
