// The three-panel frame (UI brief §3.1): library left (240px, 200–320, or a 56px rail), the screen in
// the centre, the cleaning side panel right (340px, 300–480). The dividers drag to resize, and sizes persist per
// browser. Below 1024px the side panels become slide-overs opened from the header.
import { useIsMutating } from "@tanstack/react-query";
import { Menu, PanelRight } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";
import { Outlet, useLocation, useMatch } from "react-router-dom";
import { useDataset, useLibraryEvents } from "@/api/queries";
import { ChangesPanel } from "@/components/csv/ChangesPanel";
import { CleanPlanPanel } from "@/components/dataset/CleanPlanPanel";
import { DropOverlay } from "@/components/library/DropOverlay";
import { HomeTips } from "@/components/library/HomeTips";
import { ImportPreviewDialog } from "@/components/library/ImportPreviewDialog";
import { LibraryPanel } from "@/components/library/LibraryPanel";
import { IconButton } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { LEFT, RIGHT, useUi } from "@/state/ui";
import { ErrorBoundary } from "./ErrorBoundary";
import { OfflineBanner } from "./OfflineBanner";
import { SettingsDialog } from "./SettingsDialog";

const RAIL = 56;

export function AppShell() {
  const { leftOpen, rightOpen, setLeftOpen, setRightOpen, setProgress, railed, leftWidth, rightWidth, setPanelWidth } = useUi();
  useLibraryEvents(setProgress);
  // On a dataset the right panel is Changes (App Flow §8.1), or the cleaning plan while one is open on a
  // ready dataset (§8.4); on `/`, what Sherlock does.
  const dataset = useMatch("/d/:datasetId/*");
  const { pathname } = useLocation();
  return (
    <div className="flex h-screen overflow-hidden bg-background text-foreground">
      <SidePanel side="left" open={leftOpen} onClose={() => setLeftOpen(false)} width={railed ? RAIL : leftWidth}
        onResize={railed ? undefined : (w) => setPanelWidth("left", w)}>
        <ErrorBoundary label="library" resetKey={pathname}><LibraryPanel /></ErrorBoundary>
      </SidePanel>
      <main className="@container relative flex min-w-0 flex-1 flex-col bg-card">
        <div className="absolute left-2 top-3 z-20 flex gap-1 lg:hidden">
          <IconButton label="Show your files" onClick={() => setLeftOpen(true)}><Menu /></IconButton>
        </div>
        <div className="absolute right-2 top-3 z-20 flex gap-1 lg:hidden">
          <IconButton label="Show the side panel" onClick={() => setRightOpen(true)}><PanelRight /></IconButton>
        </div>
        <OfflineBanner />
        <ErrorBoundary label="page" resetKey={pathname}><Outlet /></ErrorBoundary>
      </main>
      <SidePanel side="right" open={rightOpen} onClose={() => setRightOpen(false)} width={rightWidth}
        onResize={(w) => setPanelWidth("right", w)}>
        <ErrorBoundary label="side panel" resetKey={pathname}>
          {dataset?.params.datasetId ? <CsvSidePanel datasetId={dataset.params.datasetId} /> : <HomeTips />}
        </ErrorBoundary>
      </SidePanel>
      <DropOverlay />
      <ImportPreviewDialog />
      <SettingsDialog />
    </div>
  );
}

/** Before a dataset is ready its plan fills the centre (the offer's Clean with AI), so the panel keeps Changes. */
export function CsvSidePanel({ datasetId }: { datasetId: string }) {
  const { data: dataset } = useDataset(datasetId);
  const creating = useIsMutating({ mutationKey: ["create-plan", datasetId] }) > 0;
  if (dataset?.status === "ready" && (dataset.clean_plan_id || creating)) return <CleanPlanPanel dataset={dataset} layout="side" />;
  return <ChangesPanel datasetId={datasetId} />;
}

function SidePanel({ side, open, onClose, width, onResize, children }: {
  side: "left" | "right"; open: boolean; onClose: () => void; width: number; onResize?: (w: number) => void; children: ReactNode;
}) {
  return (
    <>
      {open && <div className="fixed inset-0 z-30 bg-scrim lg:hidden" onClick={onClose} aria-hidden />}
      <aside
        style={{ "--panel-w": `${width}px` } as CSSProperties}
        className={cn(
          "relative z-30 h-full w-[var(--panel-w)] shrink-0 bg-background max-lg:w-[min(320px,85vw)]",
          side === "left" ? "border-r border-border" : "border-l border-border",          "max-lg:fixed max-lg:top-0 max-lg:shadow-[var(--shadow-overlay)] max-lg:transition-transform max-lg:duration-[var(--duration-base)] max-lg:ease-[var(--ease)]",
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

/** A 1px divider with a wider invisible grip; dragging it resizes the panel (lg and up). A focusable
 * separator is a widget, so it carries the panel's width as its value (WAI-ARIA window splitter). */
function Divider({ side, width, onResize }: { side: "left" | "right"; width: number; onResize: (w: number) => void }) {
  const bounds = side === "left" ? LEFT : RIGHT;
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={side === "left" ? "Resize the library panel" : "Resize the side panel"}
      aria-valuenow={width}
      aria-valuemin={bounds.min}
      aria-valuemax={bounds.max}
      aria-valuetext={`${width} pixels wide`}
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
        "absolute top-0 z-10 hidden h-full w-1.5 cursor-col-resize transition-colors hover:bg-accent-soft focus-visible:bg-accent-soft lg:block",
        side === "left" ? "-right-[3px]" : "-left-[3px]",
      )}
    />
  );
}
