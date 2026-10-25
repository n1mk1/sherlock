// Menus (the widget menu, the library row menu, the dataset menu): Radix dropdown on --popover.
import * as Menu from "@radix-ui/react-dropdown-menu";
import { Check, ChevronRight } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export const MenuRoot = Menu.Root;
export const MenuTrigger = Menu.Trigger;

const surface =
  "z-50 min-w-[180px] rounded-lg border border-border bg-popover p-1 text-[13px] text-popover-foreground shadow-[var(--shadow-overlay)]";
const item =
  "flex h-8 cursor-default select-none items-center gap-2 rounded-md px-2 outline-none data-[highlighted]:bg-secondary " +
  "data-[disabled]:opacity-40 [&_svg]:size-4 [&_svg]:text-muted-foreground";

export function MenuContent({ children, align = "end" }: { children: ReactNode; align?: "start" | "end" }) {
  return (
    <Menu.Portal>
      <Menu.Content align={align} sideOffset={4} className={surface}>{children}</Menu.Content>
    </Menu.Portal>
  );
}

export function MenuItem({ children, onSelect, destructive, disabled }: {
  children: ReactNode; onSelect: () => void; destructive?: boolean; disabled?: boolean;
}) {
  return (
    // Deferred a tick so the menu has closed (and returned focus) before a dialog the item opens takes it.
    <Menu.Item disabled={disabled} onSelect={() => setTimeout(onSelect, 0)} className={cn(item, destructive && "data-[highlighted]:text-destructive")}>
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

export const MenuSeparator = () => <Menu.Separator className="my-1 h-px bg-border" />;
