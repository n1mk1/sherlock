// The chat bar (UI brief §4.8, App Flow §10.1): 680px wide, 52px tall, a context chip on the left when
// there is one, the `/` hint and the send button on the right. Chat itself arrives with the agent
// (Implementation Plan D4.3/D4.8); until then the bar shows the state-specific placeholder and stays
// disabled. The "Chat bar" setting pins it, hides it until pointed at, or hides it.
import { ArrowRight } from "lucide-react";
import { useMe } from "@/api/queries";
import { cn } from "@/lib/utils";

export function ChatBar({ placeholder, className }: { placeholder: string; className?: string }) {
  const { data: me } = useMe();
  const mode = me?.settings.chatbar ?? "pinned";
  if (mode === "hidden") return null;
  return (
    <div
      className={cn(
        "flex w-full justify-center px-6 pb-5",
        mode === "autohide" && "opacity-0 transition-opacity duration-[var(--duration-base)] hover:opacity-100 focus-within:opacity-100",
        className,
      )}
    >
      <div className="flex h-[52px] w-full max-w-[680px] items-center gap-2 rounded-[14px] border border-border bg-card pl-4 pr-1.5">
        <label className="sr-only" htmlFor="chat-input">Ask Sherlock</label>
        <input
          id="chat-input"
          disabled
          placeholder={placeholder}
          className="min-w-0 flex-1 bg-transparent text-[14px] outline-none placeholder:text-muted-foreground disabled:cursor-default"
        />
        <span aria-hidden className="font-mono text-[12px] text-muted-foreground">/</span>
        <button
          type="button"
          disabled
          aria-label="Send"
          className="inline-flex size-10 items-center justify-center rounded-[10px] bg-primary text-primary-foreground disabled:opacity-40"
        >
          <ArrowRight className="size-4" strokeWidth={1.75} />
        </button>
      </div>
    </div>
  );
}
