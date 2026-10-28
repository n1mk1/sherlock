// Menus (the library row menu, the dataset menu, the Download menu): Radix dropdown on --popover.
import * as Menu from "@radix-ui/react-dropdown-menu";
import { Check, ChevronRight } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export const MenuRoot = Menu.Root;
export const MenuTrigger = Menu.Trigger;

const surface =
  "z-50 min-w-[200px] rounded-xl bg-popover p-1.5 text-[13px] text-popover-foreground shadow-[var(--shadow-overlay)] dark:border dark:border-border " +
  "data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-[0.98]";
const item =
  "flex h-8 cursor-default select-none items-center gap-2.5 rounded-lg px-2.5 outline-none data-[highlighted]:bg-secondary " +
  "data-[disabled]:opacity-40 [&_svg]:size-4 [&_svg]:text-muted-foreground";

export function MenuContent({ children, align = "end" }: { children: ReactNode; align?: "start" | "end" }) {
  return (
    <Menu.Portal>
      <Menu.Content align={align} sideOffset={4} className={surface}>{children}</Menu.Content>
    </Menu.Portal>
  );
}

export function MenuItem({ children, onSelect, destructive, disabled, className }: {
  children: ReactNode; onSelect: () => void; destructive?: boolean; disabled?: boolean; className?: string;
}) {
  return (
    // Deferred a tick so the menu has closed (and returned focus) before a dialog the item opens takes it.
    <Menu.Item disabled={disabled} onSelect={() => setTimeout(onSelect, 0)} className={cn(item, destructive && "text-red [&_svg]:!text-red data-[highlighted]:bg-red-soft", className)}>
      {children}
    </Menu.Item>
  );
}

export function SubMenu({ label, icon, children }: { label: string; icon?: ReactNode; children: ReactNode }) {
  return (
    <Menu.Sub>
      <Menu.SubTrigger className={item}>
        {icon}
        {label}
        <ChevronRight className="ml-auto" />
      </Menu.SubTrigger>
      <Menu.Portal>
        <Menu.SubContent sideOffset={4} className={surface}>{children}</Menu.SubContent>
      </Menu.Portal>
    </Menu.Sub>
  );
}

export function MenuCheck({ checked, children, onSelect }: { checked: boolean; children: ReactNode; onSelect: () => void }) {
  return (
    <Menu.Item onSelect={onSelect} className={item}>
      <span className="inline-flex size-4 items-center justify-center">{checked && <Check />}</span>
      {children}
    </Menu.Item>
  );
}

export const MenuSeparator = () => <Menu.Separator className="mx-1 my-1.5 h-px bg-border" />;

/** An item's keyboard shortcut (or the reason it's blocked), right-aligned and muted. */
export const MenuShortcut = ({ children }: { children: ReactNode }) => (
  <span className="ml-auto pl-4 text-[11px] text-muted-foreground">{children}</span>
);

/** A group's overline inside a menu (the analysis dropdown's Explain · Predict · …). */
export const MenuLabel = ({ children }: { children: ReactNode }) => (
  <Menu.Label className="px-2.5 pb-1 pt-2 type-label">{children}</Menu.Label>
);
