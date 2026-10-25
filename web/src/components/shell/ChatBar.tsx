// The chat bar (App Flow §10.1). Chat itself arrives with the agent (Implementation Plan D4.3/D4.8);
// until then the bar shows the state-specific placeholder and stays disabled.
export function ChatBar({ placeholder }: { placeholder: string }) {
  return (
    <div className="mx-auto w-full max-w-[940px] px-4 pb-5">
      <label className="sr-only" htmlFor="chat-input">Ask Sherlock</label>
      <input
        id="chat-input"
        disabled
        placeholder={placeholder}
        className="h-[46px] w-full rounded-xl border border-border bg-card px-4 text-[14px] placeholder:text-muted-foreground disabled:cursor-default"
      />
    </div>
  );
}
