// The chat bar and thread (UI/UX brief §4.8, App Flow §10). The bar is 680px wide and 52px tall, with
// the context chip on the left (the grid's selected rows, or all rows), the `/` hint and the send button. Focus or typing opens the thread above it (at most 40% of the centre);
// Esc closes it. `/` focuses the bar when no input, cell or editor has focus. An answer streams in:
// a status line, then its blocks, then the final message with its "How do you know?" sources and, inside
// that, "How I worked it out": the model calls that made it.
// The "Chat bar" setting pins it, hides it until pointed at, or hides it.
import { ArrowRight, ChevronDown } from "lucide-react";
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { request } from "@/api/client";
import { periodActions } from "@/api/period";
import { keys, sendChat, showPlan, useMe, useThread } from "@/api/queries";
import type { AnswerBlock, CleanPlan, Dataset, Message, PlanStep, Proposal, Source } from "@/api/types";
import { BlockView } from "@/components/chat/Blocks";
import { Receipts } from "@/components/chat/Receipts";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { pendingCount, useEdits } from "@/state/edits";
import { useUi } from "@/state/ui";

// The empty thread's hint names no column, so it reads right on any file (CLAUDE.md rule 4).
export const EMPTY_THREAD_HINT =
  "Ask about the data (“the average of one column for each value of another”), find rows (“the rows where …”), " +
  "ask for a chart (“a chart of … by …”), ask what drives a column, or tell it what to change (“trim the spaces " +
  "in …”): you see the code first, and OK runs it.";

export function ChatBar({ placeholder, className, dataset }: {
  placeholder: string; className?: string; dataset?: Dataset;
}) {
  const { data: me } = useMe();
  const mode = me?.settings.chatbar ?? "pinned";
  if (mode === "hidden") return null;
  const usable = !!dataset && dataset.status !== "profiling" && dataset.status !== "failed";
  return (
    <div
      className={cn(
        "relative flex w-full flex-col items-center px-6 pb-5",
        mode === "autohide" && "opacity-0 transition-opacity duration-[var(--duration-base)] hover:opacity-100 focus-within:opacity-100",
        className,
      )}
    >
      {usable ? <LiveBar dataset={dataset} placeholder={placeholder} /> : <Bar placeholder={placeholder} />}
    </div>
  );
}

function Bar({ placeholder }: { placeholder: string }) {
  return (
    <div className="flex h-[52px] w-full max-w-[680px] items-center gap-2 rounded-[14px] border border-border bg-card pl-4 pr-1.5">
      <label className="sr-only" htmlFor="chat-input">Ask Sherlock</label>
      <input id="chat-input" disabled placeholder={placeholder}
        className="min-w-0 flex-1 bg-transparent text-[14px] outline-none placeholder:text-muted-foreground disabled:cursor-default" />
      <span aria-hidden className="font-mono text-[12px] text-muted-foreground">/</span>
      <button type="button" disabled aria-label="Send"
        className="inline-flex size-10 items-center justify-center rounded-[10px] bg-primary text-primary-foreground disabled:opacity-40">
        <ArrowRight className="size-4" strokeWidth={1.75} />
      </button>
    </div>
  );
}

interface Pending {
  text: string;
  status: string;
  blocks: AnswerBlock[];
  plan?: PlanStep[];
}

/** The thread once the saved answer arrives: the question (a local stand-in until the refetch brings
 * the saved one) and the answer. The streamed copy goes at once, so the answer shows once even while
 * the stream stays open for the thread summary that follows it (TRD §8.1 step 1). */
export function withAnswer(list: Message[] | undefined, question: string, answer: Message): Message[] {
  const asked: Message = { id: `local-${answer.id}`, role: "user", text: question, blocks: [], sources: [],
    created_at: answer.created_at, clarification_of: null };
  return [...(list ?? []), asked, answer];
}

function LiveBar({ dataset, placeholder }: { dataset: Dataset; placeholder: string }) {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const { chatOpen: open, setChatOpen: setOpen } = useUi();
  const thread = useThread(dataset.id);
  const [text, setText] = useState("");
  const [pending, setPending] = useState<Pending | null>(null);
  const [busy, setBusy] = useState(false); // from send until the stream ends, which can be after the answer shows
  const [queued, setQueued] = useState<string[]>([]); // sent while busy: they go one by one once it ends
  const csvSelection = useUi((s) => s.csvSelection);
  const planId = useUi((s) => s.planId); // a cleaning plan is open: the chat can change it (App Flow §10)
  const openExport = useUi((s) => s.openExport);

  // `/` focuses the bar when nothing editable has focus (PRD §7.11).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      const editing = t && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName));
      if (e.key === "/" && !editing && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        input.current?.focus();
        setOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setOpen]);

  const send = async (message: string, extra: Record<string, unknown> = {}) => {
    // The context is the grid's selection and the open plan (`tab` stays in the request's shape; the
    // server ignores it).
    const body = {
      text: message,
      context: {
        tab: "csv",
        ...(csvSelection ? { selected_cells: { ...csvSelection, row_ids: csvSelection.row_ids.slice(0, 500) } } : {}),
        ...(planId ? { plan_id: planId } : {}),
      },
      ...extra,
    };
    setOpen(true);
    setBusy(true);
    setPending({ text: message, status: "Thinking…", blocks: [] });
    try {
      await sendChat(dataset.id, body, ({ type, data }) => {
        if (type === "status") setPending((p) => p && { ...p, status: String(data.text) });
        else if (type === "block") setPending((p) => p && { ...p, blocks: [...p.blocks, data as unknown as AnswerBlock] });
        else if (type === "plan") setPending((p) => p && { ...p, plan: data.steps as PlanStep[] });
        else if (type === "plan.step") {
          const { index, status } = data as { index: number; status: PlanStep["status"] };
          setPending((p) => (p?.plan ? { ...p, plan: p.plan.map((s, i) => (i === index ? { ...s, status } : s)) } : p));
        } else if (type === "message") {
          const m = data as unknown as Message;
          qc.setQueryData<Message[]>(keys.chat(dataset.id), (list) => withAnswer(list, message, m));
          setPending(null); // the saved answer replaces the streamed one, so it never shows twice
          // "Export a notebook": the dialog opens with the options the message asked for (App Flow §17.1).
          const exp = m.actions?.find((a) => a.kind === "open_export");
          if (exp) openExport(exp.options ?? null);
        }
      });
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setPending(null);
      setBusy(false);
      qc.invalidateQueries({ queryKey: keys.chat(dataset.id) }); // the saved user message and its reply
    }
  };

  // The questions typed while an answer was being written, in order, one at a time.
  useEffect(() => {
    if (busy || !queued.length) return;
    setQueued(queued.slice(1));
    void send(queued[0]);
  }, [busy, queued]); // eslint-disable-line react-hooks/exhaustive-deps -- send reads the latest context

  const submit = () => {
    const message = text.trim();
    if (!message) return;
    setText("");
    if (busy) {
      setQueued((q) => [...q, message]); // shown in the thread as queued until its turn (UI brief §4.8)
      setOpen(true);
    } else void send(message);
  };
  const unqueue = (i: number) => {
    if (!text) setText(queued[i]); // back in the bar, so a cancelled question isn't lost
    setQueued((q) => q.filter((_, j) => j !== i));
  };

  const csvChip = csvSelection
    ? `${csvSelection.row_ids.length.toLocaleString()} ${csvSelection.row_ids.length === 1 ? "row" : "rows"} selected`
    : null;

  return (
    <>
      {open && (
        <Thread
          dataset={dataset}
          messages={thread.data ?? []}
          pending={pending}
          queued={queued}
          onUnqueue={unqueue}
          onClose={() => setOpen(false)}
          onChoice={(m, choice) => void send(choice, { clarification_of: m.id, choice })}
          onSend={(m) => (busy ? setQueued((q) => [...q, m]) : void send(m))}
        />
      )}
      <div className="flex h-[52px] w-full max-w-[680px] items-center gap-2 rounded-[14px] border border-border bg-card pl-2 pr-1.5 focus-within:border-border-strong">
        <span className={cn("ml-1 inline-flex h-7 shrink-0 items-center rounded-full border px-2.5 text-[12px]",
          csvChip ? "border-accent text-accent" : "border-border text-muted-foreground")}>
          {csvChip ?? "All rows"}
        </span>
        <label className="sr-only" htmlFor="chat-input">Ask Sherlock</label>
        <input
          id="chat-input"
          ref={input}
          value={text}
          placeholder={planId ? "Ask Sherlock to change the plan…" : placeholder}
          onChange={(e) => { setText(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit();
            if (e.key === "Escape") { setOpen(false); input.current?.blur(); }
          }}
          className="min-w-0 flex-1 bg-transparent text-[14px] outline-none placeholder:text-muted-foreground"
        />
        <span aria-hidden className="font-mono text-[12px] text-muted-foreground">/</span>
        <button
          type="button"
          aria-label="Send"
          title={busy ? "Sends when this answer finishes" : undefined}
          disabled={!text.trim()}
          onClick={submit}
          className="inline-flex size-10 items-center justify-center rounded-[10px] bg-primary text-primary-foreground disabled:opacity-40"
        >
          <ArrowRight className="size-4" strokeWidth={1.75} />
        </button>
      </div>
    </>
  );
}

function Thread({ dataset, messages, pending, queued, onUnqueue, onClose, onChoice, onSend }: {
  dataset: Dataset; messages: Message[]; pending: Pending | null; queued: string[]; onUnqueue: (i: number) => void;
  onClose: () => void; onChoice: (m: Message, choice: string) => void; onSend: (text: string) => void;
}) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" }); // braces: newer browsers return a promise here
  }, [messages.length, pending?.blocks.length, pending?.status, queued.length]);
  const lastId = messages[messages.length - 1]?.id;
  return (
    <div
      role="log"
      aria-label="Chat with Sherlock"
      className="absolute bottom-[84px] z-20 flex max-h-[40vh] w-[calc(100%-48px)] max-w-[680px] flex-col rounded-[16px] border border-border bg-popover shadow-[var(--shadow-overlay)]"
    >
      <div className="flex h-9 shrink-0 items-center justify-between border-b border-border pl-4 pr-1.5 text-[12px] text-muted-foreground">
        <span>Ask about {dataset.name}</span>
        <button type="button" aria-label="Close the thread" onClick={onClose} className="rounded p-1 hover:bg-secondary">
          <ChevronDown className="size-4" />
        </button>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4">
        {messages.length === 0 && !pending && (
          <p className="text-[13px] text-muted-foreground">{EMPTY_THREAD_HINT}</p>
        )}
        {messages.map((m) => (
          <MessageView key={m.id} message={m} dataset={dataset} onChoice={m.id === lastId ? onChoice : undefined} onSend={onSend} />
        ))}
        {pending && (
          <>
            <UserBubble text={pending.text} />
            <div className="flex flex-col gap-3">
              {pending.plan && <PlanView steps={pending.plan} />}
              {pending.blocks.map((b, i) => <BlockView key={i} block={b} datasetId={dataset.id} />)}
              <p className="text-[13px] italic text-muted-foreground">
                {pending.status}<span className="ml-1 inline-block animate-pulse">···</span>
              </p>
            </div>
          </>
        )}
        {queued.map((q, i) => (
          <div key={i} className="flex max-w-[80%] flex-col items-end gap-1 self-end">
            <div className="rounded-[12px] border border-dashed border-border-strong px-3 py-2 text-[14px]">{q}</div>
            <p className="text-[12px] text-muted-foreground">
              Queued: sends when this answer finishes ·{" "}
              <button type="button" onClick={() => onUnqueue(i)} className="underline hover:text-foreground">Cancel</button>
            </p>
          </div>
        ))}
        <div ref={end} />
      </div>
    </div>
  );
}

// The model card loads with the first answer that offers it, not with the page.
const ModelCardDrawer = lazy(() => import("@/components/ml/ModelCardDrawer").then((m) => ({ default: m.ModelCardDrawer })));

const UserBubble = ({ text }: { text: string }) => (
  <div className="max-w-[80%] self-end rounded-[12px] bg-secondary px-3 py-2 text-[14px]">{text}</div>
);

function MessageView({ message, dataset, onChoice, onSend }: {
  message: Message; dataset: Dataset; onChoice?: (m: Message, choice: string) => void; onSend?: (text: string) => void;
}) {
  const [card, setCard] = useState<string | null>(null);
  if (message.role === "user") return <UserBubble text={message.text} />;
  const exportAction = (message.actions ?? []).find((a) => a.kind === "open_export");
  const modelCard = (message.actions ?? []).find((a) => a.kind === "open_model_card");
  return (
    <div className="flex flex-col gap-3">
      {message.clarification && (
        <div className="flex flex-col gap-2">
          <p className="text-[14px]">{message.clarification.question}</p>
          <div className="flex flex-wrap gap-2">
            {message.clarification.options.map((o) => (
              <Button key={o} size="sm" disabled={!onChoice} onClick={() => onChoice?.(message, o)}>{o}</Button>
            ))}
          </div>
        </div>
      )}
      {message.plan && <PlanView steps={message.plan.steps} />}
      {message.blocks.map((b, i) => <BlockView key={i} block={b} datasetId={dataset.id} />)}
      {periodActions(message).map((a) => (
        <Button key={a.label} size="sm" className="self-start" disabled={!onChoice} title="Searches the news for that period; not from your data"
          onClick={() => onChoice?.(message, a.label)}>{a.label}</Button>
      ))}
      {message.proposal && <ProposalView proposal={message.proposal} dataset={dataset} onSend={onSend} />}
      {modelCard?.run_id && (
        <Button size="sm" className="self-start" onClick={() => setCard(modelCard.run_id!)}>Model card</Button>
      )}
      {exportAction && (
        <Button size="sm" className="self-start" onClick={() => useUi.getState().openExport(exportAction.options ?? null)}>
          Export notebook
        </Button>
      )}
      {message.role === "assistant" && <Sources sources={message.sources} messageId={message.id} />}
      {modelCard && card && (
        <Suspense fallback={null}><ModelCardDrawer datasetId={dataset.id} runId={card} onClose={() => setCard(null)} /></Suspense>
      )}
    </div>
  );
}

/** A multi-step answer's plan (PRD ASK-7): each step with its state as the answer streams. */
function PlanView({ steps }: { steps: PlanStep[] }) {
  const mark = { pending: "○", running: "◌", done: "✓", failed: "×" } as const;
  return (
    <ol aria-label="Plan" className="flex flex-col gap-1 rounded-lg border border-border px-3 py-2 text-[13px]">
      {steps.map((s, i) => (
        <li key={i} className={cn("flex gap-2", s.status === "pending" && "text-muted-foreground", s.status === "failed" && "text-warning")}>
          <span aria-hidden className={cn("w-3 text-center", s.status === "done" && "text-accent", s.status === "running" && "animate-pulse")}>
            {mark[s.status]}
          </span>
          <span>{s.text}</span>
          <span className="sr-only">({s.status})</span>
        </li>
      ))}
    </ol>
  );
}

/** A proposed change (PRD ASK-10): what would change, with Approve and Reject. Nothing applies before.
 * Approving a clean opens the cleaning plan for those rows; the user starts it (PRD CLEAN-1). A cleaning command
 * shows its code and the effect of its dry run, with OK and Cancel (docs/plans/chat-commands.md). */
export function ProposalView({ proposal, dataset, onSend }: {
  proposal: Proposal; dataset: Dataset; onSend?: (text: string) => void;
}) {
  if (proposal.kind === "clean_step" || proposal.kind === "computed_column") {
    return <CommandView proposal={proposal} dataset={dataset} onSend={onSend} />;
  }
  return <EditProposalView proposal={proposal} dataset={dataset} />;
}

function EditProposalView({ proposal, dataset }: { proposal: Proposal; dataset: Dataset }) {
  const qc = useQueryClient();
  const setRightOpen = useUi((s) => s.setRightOpen);
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const decide = async (what: "approve" | "reject") => {
    setBusy(what);
    try {
      const out = await request<{ version?: number } & Partial<CleanPlan>>("POST", `/api/v1/proposals/${proposal.id}/${what}`, what === "approve" ? {} : undefined);
      if (what === "approve" && proposal.kind === "edit_cells") toast(`Saved as v${out?.version}. Undo it from the Changes panel.`);
      if (what === "approve" && proposal.kind === "clean_selection" && out?.id) {
        showPlan(qc, dataset.id, out as CleanPlan);
        setRightOpen(true);
        toast("The cleaning plan is open for those rows. Look it over, then press Start cleaning.");
      }
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(null);
      qc.invalidateQueries({ queryKey: keys.chat(dataset.id) });
      qc.invalidateQueries({ queryKey: keys.jobs(dataset.id) });
    }
  };
  const edits = proposal.edits ?? [];
  const label = {
    pending: null, approved: "Approved", rejected: "Rejected", expired: "Expired: the data changed since", queued: null, failed: null,
  }[proposal.status];
  return (
    <div className="flex flex-col gap-2 rounded-[12px] border border-dashed border-accent p-3 text-[13px]">
      <p className="font-medium">{proposal.summary}</p>
      {edits.length > 0 && (
        <table className="w-full text-left text-[12px]">
          <thead className="text-muted-foreground">
            <tr><th className="font-normal">Row</th><th className="font-normal">Column</th><th className="font-normal">Now</th><th className="font-normal">After</th></tr>
          </thead>
          <tbody className="font-mono">
            {edits.slice(0, 20).map((e) => (
              <tr key={`${e.row_id}:${e.column}`}>
                <td>{e.row_id}</td><td className="font-sans">{e.column}</td>
                <td className="text-muted-foreground line-through">{e.before === null ? "empty" : String(e.before)}</td>
                <td>{e.value === null ? "empty" : e.value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {edits.length > 20 && <p className="text-muted-foreground">and {edits.length - 20} more</p>}
      {proposal.status === "pending" ? (
        <div className="flex gap-2">
          <Button size="sm" variant="primary" loading={busy === "approve"} disabled={!!busy} onClick={() => void decide("approve")}>Approve</Button>
          <Button size="sm" variant="ghost" loading={busy === "reject"} disabled={!!busy} onClick={() => void decide("reject")}>Reject</Button>
        </div>
      ) : (
        <p className={cn("text-[12px]", proposal.status === "approved" ? "text-accent" : "text-muted-foreground")}>{label}</p>
      )}
    </div>
  );
}

const CODE_FOLD_LINES = 15; // longer code shows this many lines until "Show all"

type RunAnswer = { step?: { id: string }; version?: number; refreshed?: Proposal; queued?: Proposal };

/** A cleaning command: the code that will run, what its dry run changed, the checks it passed, then Cancel and
 * OK. OK runs the code on the data as it is then: saved as one step (Undo in the toolbar), re-checked when the
 * data changed since, or queued while a clean runs. The rest of the message, if any, is sent after. */
function CommandView({ proposal, dataset, onSend }: {
  proposal: Proposal; dataset: Dataset; onSend?: (text: string) => void;
}) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [showAll, setShowAll] = useState(false);
  const pendingEdits = useEdits((s) => pendingCount(s.buffers[dataset.id]));
  const decide = async (what: "approve" | "reject") => {
    if (what === "approve" && pendingEdits > 0) {
      toast(`You have ${pendingEdits} unsaved ${pendingEdits === 1 ? "edit" : "edits"} in the grid. Save or discard them first, then press OK.`);
      return;
    }
    setBusy(what);
    try {
      const out = await request<RunAnswer>("POST", `/api/v1/proposals/${proposal.id}/${what}`, what === "approve" ? {} : undefined);
      if (what === "approve" && out?.version) {
        toast(`Done · saved as v${out.version}. Press Undo in the toolbar (Ctrl+Z) to take it back.`);
        qc.invalidateQueries({ queryKey: keys.dataset(dataset.id) });
        qc.invalidateQueries({ queryKey: keys.history(dataset.id) });
        if (proposal.then && onSend) onSend(proposal.then);
      } else if (out?.refreshed) {
        toast(`The data changed since, so I checked again on v${out.refreshed.rechecked_on}: the card shows the new effect. Press OK to run it.`);
      } else if (out?.queued) {
        toast("Cleaning is running: this runs as soon as it finishes.");
      }
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(null);
      qc.invalidateQueries({ queryKey: keys.chat(dataset.id) });
    }
  };
  const rows = proposal.before_after ?? [];
  // cells_changed leaves out a new column's cells, so the ones shown from it don't count against it
  const more = proposal.impact.cells_changed - rows.slice(0, 8).filter((e) => !(proposal.impact.columns_added ?? []).includes(e.column)).length;
  const codeLines = (proposal.code ?? "").split("\n");
  const shownCode = showAll ? proposal.code : codeLines.slice(0, CODE_FOLD_LINES).join("\n");
  const status = {
    pending: null, approved: "Done · saved as a step you can undo", rejected: "Cancelled", expired: "Expired",
    queued: "Waiting for cleaning to finish", failed: `Couldn't run: ${proposal.error ?? "a check failed"}`,
  }[proposal.status];
  return (
    <div className="flex flex-col gap-2 rounded-[12px] border border-dashed border-accent p-3 text-[13px]" aria-label="Proposed change">
      {proposal.reading ? (
        <>
          <p className="font-medium">{proposal.reading}</p>
          <p className="text-[12px] text-muted-foreground">{proposal.summary}</p>
        </>
      ) : (
        <p className="font-medium">{proposal.summary}</p>
      )}
      {proposal.rechecked_on && proposal.status === "pending" && (
        <p className="text-[12px] text-warning">Re-checked on v{proposal.rechecked_on}, since the data changed.</p>
      )}
      {proposal.code && (
        <div className="flex flex-col items-start gap-1">
          <pre aria-label="The code that will run" className="max-h-48 w-full overflow-auto whitespace-pre rounded-md bg-muted p-2 font-mono text-[12px]">{shownCode}</pre>
          {codeLines.length > CODE_FOLD_LINES && (
            <button type="button" className="text-[12px] text-accent hover:underline" onClick={() => setShowAll((v) => !v)}>
              {showAll ? "Show less" : `Show all (${codeLines.length} lines)`}
            </button>
          )}
        </div>
      )}
      {rows.length > 0 && (
        <table className="w-full text-left text-[12px]">
          <thead className="text-muted-foreground">
            <tr><th className="font-normal">Row</th><th className="font-normal">Column</th><th className="font-normal">Now</th><th className="font-normal">After</th></tr>
          </thead>
          <tbody className="font-mono">
            {rows.slice(0, 8).map((e) => (
              <tr key={`${e.row_id}:${e.column}`}>
                <td>{e.row_id}</td><td className="font-sans">{e.column}</td>
                <td className="text-muted-foreground line-through">{e.old === null ? "empty" : e.old}</td>
                <td>{e.new === null ? "empty" : e.new}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {more > 0 && (
        <p className="text-[12px] text-muted-foreground">and {more.toLocaleString()} more like {more === 1 ? "this" : "these"}</p>
      )}
      {(proposal.checks ?? []).length > 0 && (
        <p className="text-[12px] text-muted-foreground">{(proposal.checks ?? []).map((c) => `✓ ${c}`).join("   ")}</p>
      )}
      {(proposal.warnings ?? []).map((w) => (
        <p key={w} className="text-[12px] text-warning">{w}</p>
      ))}
      {proposal.then && proposal.status === "pending" && (
        <p className="text-[12px] text-muted-foreground">After it runs: “{proposal.then}”</p>
      )}
      {proposal.status === "pending" ? (
        <div className="flex justify-end gap-2">
          <Button size="sm" variant="ghost" loading={busy === "reject"} disabled={!!busy} onClick={() => void decide("reject")}>Cancel</Button>
          <Button size="sm" variant="primary" loading={busy === "approve"} disabled={!!busy} onClick={() => void decide("approve")}>OK</Button>
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <p className={cn("text-[12px]", proposal.status === "approved" ? "text-accent" : proposal.status === "failed" ? "text-warning" : "text-muted-foreground")}>
            {status}
          </p>
          {proposal.status === "queued" && (
            <Button size="sm" variant="ghost" disabled={!!busy} onClick={() => void decide("reject")}>Cancel</Button>
          )}
        </div>
      )}
    </div>
  );
}

/** "How do you know?": each source's label and SQL, then the answer's receipt (every assistant message
 * has one, so a clarification or a failed answer shows its calls too). */
export function Sources({ sources, messageId }: { sources: Source[]; messageId: string }) {
  return (
    <details className="text-[13px]">
      <summary className="cursor-pointer text-accent hover:underline">How do you know?</summary>
      <div className="mt-2 flex flex-col gap-2">
        {sources.map((s, i) => (
          <div key={i} className="flex flex-col gap-1">
            {s.url ? ( // a web source (TRD §8.2 web_context): its page, opened in a new tab
              <a href={s.url} target="_blank" rel="noopener noreferrer" className="text-[12px] text-accent hover:underline">{s.label}</a>
            ) : (
              <span className="text-[12px] text-muted-foreground">{s.label}</span>
            )}
            {s.sql && <pre className="overflow-x-auto whitespace-pre-wrap rounded-md bg-muted p-2 font-mono text-[12px]">{s.sql}</pre>}
            {s.code && <pre className="overflow-x-auto whitespace-pre-wrap rounded-md bg-muted p-2 font-mono text-[12px]">{s.code}</pre>}
          </div>
        ))}
        <Receipts path={`/api/v1/chat/messages/${messageId}/calls`} />
      </div>
    </details>
  );
}
