// The three-panel frame (UI brief §3.1): library left, the screen in the centre, stories right.
// Below 1024px the side panels become slide-overs opened from the header.
import { Menu, PanelRight } from "lucide-react";
import type { ReactNode } from "react";
import { Outlet } from "react-router-dom";
import { useLibraryEvents } from "@/api/queries";
import { DropOverlay } from "@/components/library/DropOverlay";
import { ImportPreviewDialog } from "@/components/library/ImportPreviewDialog";
import { LibraryPanel } from "@/components/library/LibraryPanel";
import { cn } from "@/lib/utils";
import { useUi } from "@/state/ui";
import { SettingsDialog } from "./SettingsDialog";
import { StoriesPanel } from "./StoriesPanel";

export function AppShell() {
  const { leftOpen, rightOpen, setLeftOpen, setRightOpen, setProgress } = useUi();
  useLibraryEvents(setProgress);
  return (
    <div className="flex h-screen overflow-hidden bg-background text-foreground">
      <SidePanel side="left" open={leftOpen} onClose={() => setLeftOpen(false)} className="w-[240px]">
        <LibraryPanel />
      </SidePanel>
      <main className="@container relative flex min-w-0 flex-1 flex-col">
        <div className="absolute left-2 top-3 z-10 flex gap-1 lg:hidden">
          <IconButton label="Show your CSVs" onClick={() => setLeftOpen(true)}><Menu /></IconButton>
        </div>
        <div className="absolute right-2 top-3 z-10 flex gap-1 lg:hidden">
          <IconButton label="Show stories" onClick={() => setRightOpen(true)}><PanelRight /></IconButton>
        </div>
        <Outlet />
      </main>
      <SidePanel side="right" open={rightOpen} onClose={() => setRightOpen(false)} className="w-[340px]">
        <StoriesPanel />
      </SidePanel>
      <DropOverlay />
      <ImportPreviewDialog />
      <SettingsDialog />
    </div>
  );
}

function SidePanel({ side, open, onClose, className, children }: {
  side: "left" | "right"; open: boolean; onClose: () => void; className: string; children: ReactNode;
}) {
  return (
    <>
      {open && <div className="fixed inset-0 z-30 bg-[rgba(46,48,53,0.28)] lg:hidden" onClick={onClose} aria-hidden />}
      <aside
        className={cn(
          "z-30 h-full shrink-0 bg-background",
          side === "left" ? "border-r border-border" : "border-l border-border",
          "max-lg:fixed max-lg:top-0 max-lg:shadow-[var(--shadow-overlay)] max-lg:transition-transform max-lg:duration-[var(--duration-base)]",
          side === "left" ? "max-lg:left-0" : "max-lg:right-0",
          !open && (side === "left" ? "max-lg:-translate-x-full" : "max-lg:translate-x-full"),
          className,
        )}
      >
        {children}
      </aside>
    </>
  );
}

export function IconButton({ label, onClick, children }: { label: string; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-secondary focus-visible:outline-2 focus-visible:outline-ring [&_svg]:size-4"
    >
      {children}
    </button>
  );
}
