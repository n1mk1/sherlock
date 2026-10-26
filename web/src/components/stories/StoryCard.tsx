// A story card (UI/UX brief §4.5–§4.6, App Flow §7.4, §11): overline, badges, the headline in the
// serif face, the body with number chips (click → evidence drawer), related-widget chips, and Edit /
// Ask why. Hovering the card spotlights its widget; hovering its widget highlights the card. A card
// the user edited keeps its text; when the data changes it shows the new narration as a suggestion
// side by side (Accept · Edit · Dismiss), and says which version the user's words were written on.
import { Database, Pencil, RefreshCw, Trash2 } from "lucide-react";
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { useCurrentVersion } from "@/api/queries";
import { plainText, useCardActions } from "@/api/stories";
import type { Card, CardBody, Run } from "@/api/types";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useUi } from "@/state/ui";

const CardEditor = lazy(() => import("./CardEditor").then((m) => ({ default: m.CardEditor })));

export function Chip({ run, facts, onOpen }: { run: Extract<Run, { type: "chip" }>; facts: Card["facts"]; onOpen?: () => void }) {
  const live = run.key ? facts[run.key]?.formatted : undefined;
  const value = live ?? run.value;
  const prev = useRef(value);
  const [pulse, setPulse] = useState(false);
  useEffect(() => {
    if (prev.current !== value) {
      prev.current = value;
      setPulse(true);
      const t = setTimeout(() => setPulse(false), 400);
      return () => clearTimeout(t);
    }
  }, [value]);
  return (
    <button
      type="button"
      onClick={onOpen}
      title={run.unverified ? "Typed by you, not computed" : run.key ? facts[run.key]?.label : undefined}
      className={cn(
        "mx-px inline rounded-[6px] border px-[5px] font-mono text-[12.5px] leading-[1.6] hover:underline",
        run.unverified
          ? "border-dashed border-border-strong text-muted-foreground"
          : "border-[color-mix(in_srgb,var(--info)_35%,transparent)] bg-info-soft text-foreground",
        pulse && "bg-accent-soft transition-colors duration-[400ms]",
      )}
    >
      {value}
    </button>
  );
}

/** Whether the user typed numbers into the card (its unverified chips). */
export function hasTypedNumbers(card: Card): boolean {
  return [...card.headline.blocks, ...card.body.blocks].some((b) => b.runs.some((r) => r.type === "chip" && r.unverified));
}

/** User-written text once the data moves on (PRD STORY-7, plan 2b.7): an edited card says which version its
 * words were written on, and one with numbers typed by hand asks for them to be checked, since no code
 * keeps those numbers current. On the card in the panel and on its canvas node. */
export function UserTextBadges({ card, small = false }: { card: Card; small?: boolean }) {
  const current = useCurrentVersion(card.dataset_id);
  if (current === undefined || card.version >= current) return null;
  const typed = hasTypedNumbers(card);
  const chip = cn("inline-flex shrink-0 items-center rounded-full border px-2", small ? "h-4 text-[10px]" : "h-5 text-[11px]");
  return (
    <>
      {card.edited_by_user && (
        <span className={cn(chip, "border-border-strong text-muted-foreground")}
          title="Your words describe the data as it was then; the numbers in chips are current">
          Written on v{card.version}, data is now v{current}
        </span>
      )}
      {typed && (
        <span className={cn(chip, "border-dashed border-warning text-warning")}
          title="Numbers you typed aren't computed, so they didn't change with the data">
          Has numbers you typed; check them
        </span>
      )}
    </>
  );
}

export function Runs({ body, facts, onChip, className }: {
  body: CardBody; facts: Card["facts"]; onChip?: (id: string) => void; className?: string;
}) {
  const bullets = body.blocks.filter((b) => b.type === "bullets");
  const render = (runs: Run[]) =>
    runs.map((r, i) =>
      r.type === "chip" ? <Chip key={i} run={r} facts={facts} onOpen={onChip ? () => onChip(r.id) : undefined} />
        : r.type === "label" ? <span key={i} className="font-medium">{r.text}</span>
          : <span key={i}>{r.text}</span>);
  if (bullets.length === body.blocks.length && bullets.length) {
    return <ul className={cn("flex list-disc flex-col gap-1 pl-4", className)}>{bullets.map((b, i) => <li key={i}>{render(b.runs)}</li>)}</ul>;
  }
  return <div className={className}>{body.blocks.map((b, i) => <p key={i}>{render(b.runs)}</p>)}</div>;
}

export function StoryCard({ card, title, onEvidence }: {
  card: Card; title: string; onEvidence: (card: Card, chipId: string) => void;
}) {
  const actions = useCardActions(card.dataset_id);
  const { hoveredWidget, setHoveredWidget, setFlashWidget, setChatDraft, setFocusedWidget, setChatOpen, editLayout } = useUi();
  const [editing, setEditing] = useState<null | "card" | "suggestion">(null);
  const ref = useRef<HTMLElement>(null);
  const linked = !!card.widget_id && hoveredWidget === card.widget_id;
  const overview = card.kind === "overview";

  useEffect(() => {
    if (linked) ref.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [linked]);

  const firstChip = [...card.headline.blocks, ...card.body.blocks].flatMap((b) => b.runs).find((r) => r.type === "chip");
  const askWhy = () => {
    if (card.widget_id) setFocusedWidget(card.widget_id);
    setChatDraft(`Why ${plainText(card.headline, card.facts).replace(/\.$/, "")}?`);
    setChatOpen(true);
  };
  const err = (e: unknown) => toast.error((e as Error).message);

  return (
    <article
      ref={ref}
      aria-label={overview ? "Overview" : title}
      onMouseEnter={() => card.widget_id && !editLayout && setHoveredWidget(card.widget_id)} // off while arranging
      onMouseLeave={() => setHoveredWidget(null)}
      onClick={(e) => {
        if (card.widget_id && !(e.target as HTMLElement).closest("button, [contenteditable]")) setFlashWidget(card.widget_id);
      }}
      className={cn(
        "rounded-[16px] border bg-card px-[22px] py-5 transition-[border-color,box-shadow] duration-[var(--duration-fast)]",
        linked ? "border-accent shadow-[var(--spotlight-shadow)]" : "border-border",
        card.status === "updating" && "opacity-70",
      )}
    >
      <div className="mb-1.5 flex items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
          {overview ? "Overview" : title}
        </span>
        {card.status === "updating" && <RefreshCw className="size-3.5 animate-spin text-muted-foreground" aria-label="Updating" />}
        {card.changed_badge && (
          <button type="button" title={`Updated after v${card.version}. Click to dismiss.`}
            onClick={() => actions.dismissBadge.mutate(card.id, { onError: err })}
            className="inline-flex h-5 items-center rounded-full border border-warning px-2 text-[11px] text-warning">changed</button>
        )}
        {card.edited_by_user && <span title="Edited by you" className="inline-flex items-center gap-1 text-[11px] text-muted-foreground"><Pencil className="size-3" /> edited</span>}
        <UserTextBadges card={card} />
        {card.status === "outdated" && (
          <button type="button" onClick={() => actions.refresh.mutate(card.id, { onError: err })}
            className="inline-flex h-5 items-center rounded-full border border-warning px-2 text-[11px] text-warning">outdated, click to refresh</button>
        )}
      </div>

      {editing === "card" ? (
        <Suspense fallback={<p className="text-muted-foreground">Opening the editor…</p>}>
          <CardEditor card={card} source={{ headline: card.headline, body: card.body }}
            onCancel={() => setEditing(null)}
            onSave={(headline, body) => actions.edit.mutate({ id: card.id, headline, body }, { onSuccess: () => setEditing(null), onError: err })} />
        </Suspense>
      ) : (
        <>
          {!overview && <Runs body={card.headline} facts={card.facts} onChip={(id) => onEvidence(card, id)}
            className="font-serif text-[18px] font-semibold leading-snug" />}
          <Runs body={card.body} facts={card.facts} onChip={(id) => onEvidence(card, id)}
            className={cn("text-[14px] leading-relaxed text-foreground-2", !overview && "mt-2 flex flex-col gap-1.5")} />
        </>
      )}

      {card.suggestion && editing !== "card" && (
        <div className="mt-3 rounded-[12px] border border-dashed border-warning p-3">
          <p className="mb-1.5 text-[12px] font-semibold text-warning">The data changed. Suggested revision:</p>
          {editing === "suggestion" ? (
            <Suspense fallback={null}>
              <CardEditor card={card} source={card.suggestion} onCancel={() => setEditing(null)}
                onSave={(headline, body) => actions.edit.mutate({ id: card.id, headline, body }, {
                  onSuccess: () => { setEditing(null); actions.dismiss.mutate(card.id); }, onError: err })} />
            </Suspense>
          ) : (
            <>
              <Runs body={card.suggestion.headline} facts={card.facts} className="font-serif text-[15px] font-semibold" />
              <Runs body={card.suggestion.body} facts={card.facts} className="mt-1 text-[13px] text-foreground-2" />
              <div className="mt-2 flex gap-2">
                <Button size="sm" variant="primary" onClick={() => actions.accept.mutate(card.id, { onError: err })}>Accept</Button>
                <Button size="sm" onClick={() => setEditing("suggestion")}>Edit</Button>
                <Button size="sm" variant="ghost" onClick={() => actions.dismiss.mutate(card.id, { onError: err })}>Dismiss</Button>
              </div>
            </>
          )}
        </div>
      )}

      {card.related.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5 text-[12px] text-muted-foreground">
          Related:
          {card.related.map((r) => (
            <button key={r.widget_id} type="button"
              onMouseEnter={() => setHoveredWidget(r.widget_id)}
              onMouseLeave={() => setHoveredWidget(card.widget_id)}
              onClick={() => setFlashWidget(r.widget_id)}
              className="inline-flex h-6 items-center rounded-full border border-border bg-secondary px-2.5 hover:border-accent">
              {r.title}
            </button>
          ))}
        </div>
      )}
      {editing !== "card" && (
        <div className="mt-3 flex items-center gap-2 border-t border-border pt-2.5">
          <button type="button" disabled={!firstChip} onClick={() => firstChip?.type === "chip" && onEvidence(card, firstChip.id)}
            className="inline-flex items-center gap-1.5 text-[12px] text-accent hover:underline disabled:opacity-40">
            <Database className="size-3.5" /> Evidence
          </button>
          <span className="flex-1" />
          <Button size="sm" variant="ghost" onClick={() => setEditing("card")}>Edit</Button>
          <Button size="sm" variant="ghost" aria-label="Delete this card" title="Delete this card"
            onClick={() => actions.remove.mutate(card.id, {
              onSuccess: () => toast("Card deleted", { duration: 10_000, action: { label: "Undo", onClick: () => actions.restore.mutate(card.id) } }),
              onError: err,
            })}>
            <Trash2 />
          </Button>
          {!overview && <Button size="sm" variant="ghost" onClick={askWhy}>Ask why</Button>}
        </div>
      )}
    </article>
  );
}
