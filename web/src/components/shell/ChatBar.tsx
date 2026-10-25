// The chat bar and thread (UI/UX brief §4.8, App Flow §10). The bar is 680px wide and 52px tall, with
// a context chip on the left when there is one (the global filter or the focused widget), the `/`
// hint and the send button. Focus or typing opens the thread above it (at most 40% of the centre);
// Esc closes it. `/` focuses the bar when no input, cell or editor has focus. An answer streams in:
// a status line, then its blocks, then the final message with its "How do you know?" sources.
// The "Chat bar" setting pins it, hides it until pointed at, or hides it.
import { ArrowRight, ChevronDown, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { filterParam, keys, sendChat, useMe, usePin, useThread, useWidgets } from "@/api/queries";
import type { AnswerBlock, Dataset, Message, Source, Tab } from "@/api/types";
import { BlockView } from "@/components/chat/Blocks";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useFilters, useGlobalFilter } from "@/state/filters";
import { useUi } from "@/state/ui";

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
      },
      ...extra,
    };
    setOpen(true);
    setPending({ text: message, status: "Thinking…", blocks: [] });
    try {
      await sendChat(dataset.id, body, ({ type, data }) => {
        if (type === "status") setPending((p) => p && { ...p, status: String(data.text) });
        else if (type === "block") setPending((p) => p && { ...p, blocks: [...p.blocks, data as unknown as AnswerBlock] });
        else if (type === "message") {
          qc.setQueryData<Message[]>(keys.chat(dataset.id), (list) => [...(list ?? []), data as unknown as Message]);
          if ((data as unknown as Message).actions?.some((a) => a.kind === "open_widget")) {
            qc.invalidateQueries({ queryKey: keys.widgets(dataset.id) });
          }
        }
      });
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setPending(null);
      qc.invalidateQueries({ queryKey: keys.chat(dataset.id) }); // the saved user message and its reply
    }
  };

  const submit = () => {
    const message = text.trim();
    if (!message || pending) return;
    setText("");
    void send(message);
  };

  const chip = tab === "dashboard" && (filter || focused)
    ? { label: filter ? `${filter.col} = ${String(filter.value)}` : focused!.title, clear: () => (filter ? clearFilter(dataset.id) : setFocusedWidget(null)) }
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
          <span className="ml-1 inline-flex h-7 shrink-0 items-center rounded-full border border-border px-2.5 text-[12px] text-muted-foreground">All rows</span>
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
          <p className="text-[13px] text-muted-foreground">
            Ask about the data (“average fare by class”), find rows, or ask for a widget (“add a chart of fare by port to the dashboard”).
          </p>
        )}
        {messages.map((m) => (
          <MessageView key={m.id} message={m} dataset={dataset} onChoice={m.id === lastId ? onChoice : undefined} />
        ))}
        {pending && (
          <>
            <UserBubble text={pending.text} />
            <div className="flex flex-col gap-3">
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

const UserBubble = ({ text }: { text: string }) => (
  <div className="max-w-[80%] self-end rounded-[12px] bg-secondary px-3 py-2 text-[14px]">{text}</div>
);

function MessageView({ message, dataset, onChoice }: {
  message: Message; dataset: Dataset; onChoice?: (m: Message, choice: string) => void;
}) {
  const pin = usePin(dataset.id);
  const navigate = useNavigate();
  if (message.role === "user") return <UserBubble text={message.text} />;
  const pinnable = new Set((message.actions ?? []).filter((a) => a.kind === "pin").map((a) => a.block_index));
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
      {message.blocks.map((b, i) => (
        <BlockView
          key={i}
          block={b}
          datasetId={dataset.id}
          pinning={pin.isPending && pin.variables?.blockIndex === i}
          onPin={pinnable.has(i) ? () => pin.mutate({ messageId: message.id, blockIndex: i }, {
            onSuccess: (w) => toast(`Pinned “${w.title}” to the dashboard`, { action: { label: "Open", onClick: () => navigate(`/d/${dataset.id}/dashboard`) } }),
            onError: (e) => toast.error((e as Error).message),
          }) : undefined}
        />
      ))}
      {message.sources.length > 0 && <Sources sources={message.sources} />}
    </div>
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
