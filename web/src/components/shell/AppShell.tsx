// The three-panel frame (UI brief §3.1): library left (240px, 200–320, or a 56px rail), the screen in
// the centre, stories right (340px, 300–480). The dividers drag to resize, and sizes persist per
// browser. Below 1024px the side panels become slide-overs opened from the header.
import { Menu, PanelRight } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";
import { Outlet, useMatch } from "react-router-dom";
import { useLibraryEvents } from "@/api/queries";
import { ChangesPanel } from "@/components/csv/ChangesPanel";
import { DropOverlay } from "@/components/library/DropOverlay";
import { ImportPreviewDialog } from "@/components/library/ImportPreviewDialog";
import { LibraryPanel } from "@/components/library/LibraryPanel";
import { cn } from "@/lib/utils";
import { useUi } from "@/state/ui";
import { SettingsDialog } from "./SettingsDialog";
import { StoriesPanel } from "@/components/stories/StoriesPanel";

const RAIL = 56;

export function AppShell() {
  const { leftOpen, rightOpen, setLeftOpen, setRightOpen, setProgress, railed, leftWidth, rightWidth, setPanelWidth } = useUi();
  useLibraryEvents(setProgress);
  // The right panel is Changes on the CSV tab (App Flow §8.1), stories elsewhere.
  const csv = useMatch("/d/:datasetId/csv");
  return (
    <div className="flex h-screen overflow-hidden bg-background text-foreground">
      <SidePanel side="left" open={leftOpen} onClose={() => setLeftOpen(false)} width={railed ? RAIL : leftWidth}
        onResize={railed ? undefined : (w) => setPanelWidth("left", w)}>
        <LibraryPanel />
      </SidePanel>
      <main className="@container relative flex min-w-0 flex-1 flex-col">
        <div className="absolute left-2 top-3 z-20 flex gap-1 lg:hidden">
          <IconButton label="Show your CSVs" onClick={() => setLeftOpen(true)}><Menu /></IconButton>
        </div>
        <div className="absolute right-2 top-3 z-20 flex gap-1 lg:hidden">
          <IconButton label="Show stories" onClick={() => setRightOpen(true)}><PanelRight /></IconButton>
        </div>
        <Outlet />
      </main>
      <SidePanel side="right" open={rightOpen} onClose={() => setRightOpen(false)} width={rightWidth}
        onResize={(w) => setPanelWidth("right", w)}>
        {csv?.params.datasetId ? <ChangesPanel datasetId={csv.params.datasetId} /> : <StoriesPanel />}
      </SidePanel>
      <DropOverlay />
      <ImportPreviewDialog />
      <SettingsDialog />
    </div>
  );
}

function SidePanel({ side, open, onClose, width, onResize, children }: {
  side: "left" | "right"; open: boolean; onClose: () => void; width: number; onResize?: (w: number) => void; children: ReactNode;
}) {
  return (
    <>
      {open && <div className="fixed inset-0 z-30 bg-[rgba(46,48,53,0.28)] lg:hidden" onClick={onClose} aria-hidden />}
      <aside
        style={{ "--panel-w": `${width}px` } as CSSProperties}
        className={cn(
          "relative z-30 h-full w-[var(--panel-w)] shrink-0 bg-background max-lg:w-[min(320px,85vw)]",
          side === "left" ? "border-r border-border" : "border-l border-border",
          "max-lg:fixed max-lg:top-0 max-lg:shadow-[var(--shadow-overlay)] max-lg:transition-transform max-lg:duration-[var(--duration-base)]",
          side === "left" ? "max-lg:left-0" : "max-lg:right-0",
          !open && (side === "left" ? "max-lg:-translate-x-full" : "max-lg:translate-x-full"),
        )}
      >
        {children}
        {onResize && <Divider side={side} width={width} onResize={onResize} />}
      </aside>
    </>
  );
}

/** A 1px divider with a wider invisible grip; dragging it resizes the panel (lg and up). */
function Divider({ side, width, onResize }: { side: "left" | "right"; width: number; onResize: (w: number) => void }) {
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={side === "left" ? "Resize the library panel" : "Resize the stories panel"}
      tabIndex={0}
      onKeyDown={(e) => {
        const step = e.key === "ArrowLeft" ? -16 : e.key === "ArrowRight" ? 16 : 0;
        if (step) onResize(width + (side === "left" ? step : -step));
      }}
      onPointerDown={(e) => {
        e.preventDefault();
        const startX = e.clientX;
        const move = (ev: PointerEvent) => onResize(width + (side === "left" ? ev.clientX - startX : startX - ev.clientX));
        const up = () => {
          window.removeEventListener("pointermove", move);
          window.removeEventListener("pointerup", up);
        };
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", up);
      }}
      className={cn(
        "absolute top-0 z-10 hidden h-full w-1.5 cursor-col-resize hover:bg-accent-soft focus-visible:bg-accent-soft lg:block",
        side === "left" ? "-right-[3px]" : "-left-[3px]",
      )}
    />
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
