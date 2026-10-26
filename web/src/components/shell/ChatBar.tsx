// The chat bar and thread (UI/UX brief §4.8, App Flow §10). The bar is 680px wide and 52px tall, with
// a context chip on the left when there is one (the global filter or the focused widget), the `/`
// hint and the send button. Focus or typing opens the thread above it (at most 40% of the centre);
// Esc closes it. `/` focuses the bar when no input, cell or editor has focus. An answer streams in:
// a status line, then its blocks, then the final message with its "How do you know?" sources.
// The "Chat bar" setting pins it, hides it until pointed at, or hides it.
import { ArrowRight, ChevronDown, Workflow, X } from "lucide-react";
import { lazy, Suspense, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { request } from "@/api/client";
import { filterParam, keys, sendChat, useAddToFlow, useMe, usePin, useThread, useWidgets } from "@/api/queries";
import type { AnswerBlock, Dataset, Message, PlanStep, Proposal, Source, Tab } from "@/api/types";
import { BlockView } from "@/components/chat/Blocks";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useFilters, useGlobalFilter } from "@/state/filters";
import { useFlow } from "@/state/flow";
import { useUi } from "@/state/ui";

// The empty thread's hint names no column, so it reads right on any file (CLAUDE.md rule 4).
export const EMPTY_THREAD_HINT =
  "Ask about the data (“the average of one column for each value of another”), find rows (“the rows where …”), " +
  "or ask for a widget (“add a chart of … by … to the dashboard”).";

export function ChatBar({ placeholder, className, dataset, tab }: {
  placeholder: string; className?: string; dataset?: Dataset; tab?: Tab;
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
      {usable ? <LiveBar dataset={dataset} tab={tab ?? "dashboard"} placeholder={placeholder} /> : <Bar placeholder={placeholder} />}
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

function LiveBar({ dataset, tab, placeholder }: { dataset: Dataset; tab: Tab; placeholder: string }) {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const { chatOpen: open, setChatOpen: setOpen, focusedWidgetId, setFocusedWidget } = useUi();
  const filter = useGlobalFilter(dataset.id);
  const clearFilter = useFilters((s) => s.clear);
  const thread = useThread(dataset.id);
  const widgets = useWidgets(dataset.id);
  const [text, setText] = useState("");
  const { chatDraft, setChatDraft } = useUi();
  // "Ask why" on a story card fills the bar (App Flow §7.4).
  useEffect(() => {
    if (chatDraft === null) return;
    setText(chatDraft);
    setChatDraft(null);
    setOpen(true);
    input.current?.focus();
  }, [chatDraft, setChatDraft, setOpen]);
  const [pending, setPending] = useState<Pending | null>(null);
  const focused = widgets.data?.widgets.find((w) => w.id === focusedWidgetId);
  const selectedCards = useFlow((s) => s.selectedCardIds);
  const csvSelection = useUi((s) => s.csvSelection);
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
    const body = {
      text: message,
      context: {
        tab,
        ...(tab === "dashboard" && filter ? { global_filter: JSON.parse(filterParam(filter)) } : {}),
        ...(tab === "dashboard" && focused ? { focused_widget_id: focused.id } : {}),
        ...(tab === "flow" ? { selected_card_ids: selectedCards } : {}),
        ...(tab === "csv" && csvSelection ? { selected_cells: { ...csvSelection, row_ids: csvSelection.row_ids.slice(0, 500) } } : {}),
      },
      ...extra,
    };
    setOpen(true);
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
          qc.setQueryData<Message[]>(keys.chat(dataset.id), (list) => [...(list ?? []), m]);
          if (m.actions?.some((a) => a.kind === "open_widget")) {
            qc.invalidateQueries({ queryKey: keys.widgets(dataset.id) });
          }
          // "Export a notebook": the dialog opens with the options the message asked for (App Flow §17.1).
          const exp = m.actions?.find((a) => a.kind === "open_export");
          if (exp) openExport(exp.options ?? null);
        }
      });
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setPending(null);
      qc.invalidateQueries({ queryKey: keys.chat(dataset.id) }); // the saved user message and its reply
    }
  };

  // A message another part of the page asked to send (the Flow header's "Make sense of this").
  const { chatOutbox, sendChat: queueChat } = useUi();
  useEffect(() => {
    if (chatOutbox === null || pending) return;
    queueChat(null);
    void send(chatOutbox);
  }, [chatOutbox]); // eslint-disable-line react-hooks/exhaustive-deps -- send reads the latest context

  const submit = () => {
    const message = text.trim();
    if (!message || pending) return;
    setText("");
    void send(message);
  };

  const csvChip = tab === "csv" && csvSelection
    ? `${csvSelection.row_ids.length.toLocaleString()} ${csvSelection.row_ids.length === 1 ? "row" : "rows"} selected`
    : null;
  const chip = tab === "dashboard" && (filter || focused)
    ? { label: filter ? `${filter.col} = ${String(filter.value)}` : focused!.title, clear: () => (filter ? clearFilter(dataset.id) : setFocusedWidget(null)) }
    : null;
  // On the canvas the selected cards are the context (App Flow §12.1).
  const flowChip = tab === "flow"
    ? (selectedCards.length ? `${selectedCards.length} ${selectedCards.length === 1 ? "card" : "cards"} selected` : "Whole canvas")
    : null;

  return (
    <>
      {open && (
        <Thread
          dataset={dataset}
          messages={thread.data ?? []}
          pending={pending}
          onClose={() => setOpen(false)}
          onChoice={(m, choice) => void send(choice, { clarification_of: m.id, choice })}
        />
      )}
      <div className="flex h-[52px] w-full max-w-[680px] items-center gap-2 rounded-[14px] border border-border bg-card pl-2 pr-1.5 focus-within:border-border-strong">
        {chip ? (
          <button
            type="button"
            onClick={chip.clear}
            title="Clear the context"
            className="ml-1 inline-flex h-7 max-w-[40%] shrink-0 items-center gap-1 truncate rounded-full border border-border bg-secondary px-2.5 text-[12px] text-muted-foreground hover:text-foreground"
          >
            <span className="truncate">{chip.label}</span>
            <X className="size-3 shrink-0" />
          </button>
        ) : (
          <span className={cn("ml-1 inline-flex h-7 shrink-0 items-center rounded-full border px-2.5 text-[12px]",
            (flowChip && selectedCards.length) || csvChip ? "border-accent text-accent" : "border-border text-muted-foreground")}>
            {flowChip ?? csvChip ?? "All rows"}
          </span>
        )}
        <label className="sr-only" htmlFor="chat-input">Ask Sherlock</label>
        <input
          id="chat-input"
          ref={input}
          value={text}
          placeholder={placeholder}
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
          disabled={!text.trim() || !!pending}
          onClick={submit}
          className="inline-flex size-10 items-center justify-center rounded-[10px] bg-primary text-primary-foreground disabled:opacity-40"
        >
          <ArrowRight className="size-4" strokeWidth={1.75} />
        </button>
      </div>
    </>
  );
}

function Thread({ dataset, messages, pending, onClose, onChoice }: {
  dataset: Dataset; messages: Message[]; pending: Pending | null; onClose: () => void;
  onChoice: (m: Message, choice: string) => void;
}) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" }); // braces: newer browsers return a promise here
  }, [messages.length, pending?.blocks.length, pending?.status]);
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
          <MessageView key={m.id} message={m} dataset={dataset} onChoice={m.id === lastId ? onChoice : undefined} />
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

function MessageView({ message, dataset, onChoice }: {
  message: Message; dataset: Dataset; onChoice?: (m: Message, choice: string) => void;
}) {
  const pin = usePin(dataset.id);
  const addToFlow = useAddToFlow(dataset.id);
  const navigate = useNavigate();
  const [card, setCard] = useState<string | null>(null);
  if (message.role === "user") return <UserBubble text={message.text} />;
  const pinnable = new Set((message.actions ?? []).filter((a) => a.kind === "pin").map((a) => a.block_index));
  const addable = new Set((message.actions ?? []).filter((a) => a.kind === "add_to_flow").map((a) => a.block_index));
  const undoWidget = (message.actions ?? []).find((a) => a.kind === "undo_widget");
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
      {message.blocks.map((b, i) => (
        <div key={i} className="flex flex-col gap-1.5">
          <BlockView
            block={b}
            datasetId={dataset.id}
            pinning={pin.isPending && pin.variables?.blockIndex === i}
            onPin={pinnable.has(i) ? () => pin.mutate({ messageId: message.id, blockIndex: i }, {
              onSuccess: (w) => toast(`Pinned “${w.title}” to the dashboard`, { action: { label: "Open", onClick: () => navigate(`/d/${dataset.id}/dashboard`) } }),
              onError: (e) => toast.error((e as Error).message),
            }) : undefined}
          />
          {addable.has(i) && (
            <Button size="sm" variant="ghost" className="self-start"
              loading={addToFlow.isPending && addToFlow.variables?.blockIndex === i}
              onClick={() => addToFlow.mutate({ messageId: message.id, blockIndex: i }, {
                onSuccess: () => toast("Added to the canvas", { action: { label: "Open", onClick: () => navigate(`/d/${dataset.id}/flow`) } }),
                onError: (e) => toast.error((e as Error).message),
              })}>
              <Workflow /> Add to Flow
            </Button>
          )}
        </div>
      ))}
      {message.proposal && <ProposalView proposal={message.proposal} dataset={dataset} />}
      {modelCard?.run_id && (
        <Button size="sm" className="self-start" onClick={() => setCard(modelCard.run_id!)}>Model card</Button>
      )}
      {(undoWidget || exportAction) && (
        <div className="flex gap-2">
          {undoWidget?.widget_id && <UndoWidget widgetId={undoWidget.widget_id} datasetId={dataset.id} />}
          {exportAction && (
            <Button size="sm" className="self-start" onClick={() => useUi.getState().openExport(exportAction.options ?? null)}>
              Export notebook
            </Button>
          )}
        </div>
      )}
      {message.sources.length > 0 && <Sources sources={message.sources} />}
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

/** A proposed change (PRD ASK-10): what would change, with Approve and Reject. Nothing applies before. */
function ProposalView({ proposal, dataset }: { proposal: Proposal; dataset: Dataset }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const decide = async (what: "approve" | "reject") => {
    setBusy(what);
    try {
      const out = await request<{ version?: number; kind?: string }>("POST", `/api/v1/proposals/${proposal.id}/${what}`, what === "approve" ? {} : undefined);
      if (what === "approve") toast(proposal.kind === "edit_cells" ? `Saved as v${out?.version}. Undo it from the Changes panel.` : "Clean with AI started.");
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setBusy(null);
      qc.invalidateQueries({ queryKey: keys.chat(dataset.id) });
      qc.invalidateQueries({ queryKey: keys.jobs(dataset.id) });
    }
  };
  const edits = proposal.edits ?? [];
  const label = { pending: null, approved: "Approved", rejected: "Rejected", expired: "Expired: the data changed since" }[proposal.status];
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

function UndoWidget({ widgetId, datasetId }: { widgetId: string; datasetId: string }) {
  const qc = useQueryClient();
  const [done, setDone] = useState(false);
  return (
    <Button size="sm" className="self-start" disabled={done} onClick={async () => {
      try {
        await request("POST", `/api/v1/widgets/${widgetId}/undo`);
        setDone(true);
        qc.invalidateQueries({ queryKey: keys.widgets(datasetId) });
        toast("The widget is back as it was.");
      } catch (e) {
        toast.error((e as Error).message);
      }
    }}>{done ? "Undone" : "Undo"}</Button>
  );
}

function Sources({ sources }: { sources: Source[] }) {
  return (
    <details className="text-[13px]">
      <summary className="cursor-pointer text-accent hover:underline">How do you know?</summary>
      <div className="mt-2 flex flex-col gap-2">
        {sources.map((s, i) => (
          <div key={i} className="flex flex-col gap-1">
            <span className="text-[12px] text-muted-foreground">{s.label}</span>
            {s.sql && <pre className="overflow-x-auto whitespace-pre-wrap rounded-md bg-muted p-2 font-mono text-[12px]">{s.sql}</pre>}
          </div>
        ))}
      </div>
    </details>
  );
}
