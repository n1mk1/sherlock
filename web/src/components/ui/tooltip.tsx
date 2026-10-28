// Tooltips (UI/UX brief §4.11): Radix Tooltip in ink (inverted), body-sm, 6px 10px, a 200 ms delay and at
// most two lines, with an optional keyboard shortcut on the right, dimmed. Each tooltip carries its
// own provider, so it works anywhere without an app-wide wrapper.
import * as Tooltip from "@radix-ui/react-tooltip";
import type { ReactNode } from "react";

export function Tip({ label, shortcut, side = "top", children }: {
  label: string; shortcut?: string; side?: "top" | "bottom" | "left" | "right"; children: ReactNode;
}) {
  return (
    <Tooltip.Provider delayDuration={200}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>{children}</Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content side={side} sideOffset={6}
            className="z-50 flex max-w-[260px] items-baseline gap-3 rounded-lg bg-primary px-2.5 py-1.5 text-[12px] font-medium text-primary-foreground shadow-[var(--shadow-overlay)]">
            <span className="line-clamp-2">{label}</span>
            {shortcut && <span className="shrink-0 text-[11px] opacity-60">{shortcut}</span>}
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );
}
