// Drawers (UI brief §4.9): slide in from the right over the right panel, 420px, --popover, title row
// with ×; Esc and backdrop click close; focus is trapped and returned.
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";

export function Drawer({ open, onOpenChange, title, children }: {
  open: boolean; onOpenChange: (open: boolean) => void; title: string; children: ReactNode;
}) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-[rgba(46,48,53,0.28)] dark:bg-[rgba(0,0,0,0.5)]" />
        <DialogPrimitive.Content
          aria-describedby={undefined}
          className="fixed right-0 top-0 z-50 flex h-full w-[min(420px,100vw)] flex-col border-l border-border bg-popover text-popover-foreground shadow-[var(--shadow-overlay)]"
        >
          <div className="flex h-14 shrink-0 items-center justify-between border-b border-border px-5">
            <DialogPrimitive.Title className="text-[15px] font-semibold">{title}</DialogPrimitive.Title>
            <DialogPrimitive.Close
              className="rounded-md p-1.5 text-muted-foreground hover:bg-secondary focus-visible:outline-2 focus-visible:outline-ring"
              aria-label="Close"
            >
              <X className="size-4" />
            </DialogPrimitive.Close>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-5">{children}</div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
