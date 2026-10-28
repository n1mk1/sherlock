// Drawers: slide in from the right over the right panel, 440px, the title row with ×; Esc and backdrop
// click close; focus is trapped and returned.
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";

export function Drawer({ open, onOpenChange, title, children }: {
  open: boolean; onOpenChange: (open: boolean) => void; title: string; children: ReactNode;
}) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-scrim data-[state=open]:animate-in data-[state=open]:fade-in-0" />
        <DialogPrimitive.Content
          aria-describedby={undefined}
          className="fixed right-0 top-0 z-50 flex h-full w-[min(440px,100vw)] flex-col bg-popover text-popover-foreground shadow-[var(--shadow-overlay)] data-[state=open]:animate-in data-[state=open]:slide-in-from-right-8 dark:border-l dark:border-border"
        >
          <div className="flex h-16 shrink-0 items-center justify-between px-6">
            <DialogPrimitive.Title className="type-title">{title}</DialogPrimitive.Title>
            <DialogPrimitive.Close
              className="inline-flex size-8 items-center justify-center rounded-full text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring"
              aria-label="Close"
            >
              <X className="size-4" />
            </DialogPrimitive.Close>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-6">{children}</div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
