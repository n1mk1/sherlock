// A dataset route (App Flow §1): `/d/:id/:tab`. Until the dataset is ready, the centre shows the
// status screen for where it is (profiling, offer, cleaning, building, failed).
import { useIsMutating } from "@tanstack/react-query";
import { lazy, Suspense, useEffect, useRef } from "react";
import { Navigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { rememberTab, useDataset, useDatasetEvents, useMe } from "@/api/queries";
import type { Dataset, Tab } from "@/api/types";
import { SaveActions } from "@/components/csv/SaveActions";
import { DashboardActions, FilterChip } from "@/components/dashboard/DashboardActions";
import { FlowActions } from "@/components/flow/FlowPalette";
import { CenterHeader } from "@/components/shell/CenterHeader";
import { ChatBar } from "@/components/shell/ChatBar";
import { DatasetMenu } from "@/components/shell/DatasetMenu";
import { ErrorBoundary } from "@/components/shell/ErrorBoundary";
import { ExportDialog } from "@/components/shell/ExportDialog";
import { JobTray } from "@/components/shell/JobTray";
import { CleanPlanPanel } from "./CleanPlanPanel";
import { CleaningOffer } from "./CleaningOffer";
import { CleaningProgress } from "./CleaningProgress";
import { OfferActions } from "./OfferActions";
import { useUi } from "@/state/ui";
import { BuildingScreen, FailedScreen, ProfilingScreen } from "./StatusScreens";

const TABS: Tab[] = ["csv", "dashboard", "flow"];
// The dashboard (grid and chart libraries) loads when its tab first opens.
const Dashboard = lazy(() => import("@/components/dashboard/Dashboard").then((m) => ({ default: m.Dashboard })));
// So does the CSV grid (Glide Data Grid), when the CSV tab first opens.
const CsvTab = lazy(() => import("@/components/csv/CsvTab").then((m) => ({ default: m.CsvTab })));
// And the Flow canvas (React Flow), when the Flow tab first opens.
const FlowTab = lazy(() => import("@/components/flow/FlowTab").then((m) => ({ default: m.FlowTab })));

export function DatasetRedirect() {
  const { datasetId } = useParams();
  const { data: dataset, error } = useDataset(datasetId);
  const { data: me } = useMe();
  if (error) return <Gone />;
  if (!dataset || !me) return null;
  const tab = dataset.last_tab ?? me.settings.default_tab ?? "dashboard";
  return <Navigate to={`/d/${dataset.id}/${tab}`} replace />;
}

function Gone() {
  useEffect(() => {
    toast("That CSV is no longer available.");
  }, []);
  return <Navigate to="/" replace state={{ stay: true }} />;
}

export function DatasetPage() {
  const { datasetId, tab: rawTab } = useParams();
  const { data: dataset, error } = useDataset(datasetId);
  const scroller = useRef<HTMLDivElement>(null);
  useRememberScroll(scroller, datasetId && rawTab ? `${datasetId}.${rawTab}` : null);
  if (error) return <Gone />;
  if (!dataset) return null;
  const tab = (TABS as string[]).includes(rawTab ?? "") ? (rawTab as Tab) : "dashboard";
  const ready = dataset.status === "ready";
  const enabled = (t: Tab) => {
    if (ready) return null;
    if (t === "csv" && dataset.current_version > 0 && dataset.status !== "profiling") return null;
    return dataset.status === "cleaning" ? "Available after cleaning" : "Available once the dataset is ready";
  };
  // A tab that isn't available yet shows the status screen instead of its content.
  const showTab = enabled(tab) === null && (ready || tab === "csv");
  const onDashboard = showTab && tab === "dashboard";
  const onCsv = showTab && tab === "csv";
  const onFlow = showTab && tab === "flow";
  return (
    <div className="flex h-full min-h-0 flex-col">
      <RememberTab datasetId={dataset.id} tab={tab} active={showTab} />
      <DatasetEvents datasetId={dataset.id} />
      <ExportDialog dataset={dataset} />
      <CenterHeader
        dataset={dataset}
        tab={tab}
        enabled={enabled}
        chips={onDashboard ? <FilterChip datasetId={dataset.id} /> : null}
        actions={
          <>
            {onCsv && <SaveActions dataset={dataset} />}
            {onDashboard && <DashboardActions />}
            {onFlow && <FlowActions />}
            <JobTray />
            <DatasetMenu dataset={dataset} />
          </>
        }
      />
      <CascadeLine datasetId={dataset.id} />
      <div ref={scroller} className={(tab === "csv" || tab === "flow") && showTab ? "flex min-h-0 flex-1 flex-col" : "flex min-h-0 flex-1 flex-col overflow-y-auto"}>
        <ErrorBoundary label={tab === "csv" ? "CSV tab" : tab === "flow" ? "canvas" : "dashboard"} resetKey={`${dataset.id}:${tab}`}>
          {showTab ? <TabContent dataset={dataset} tab={tab} /> : <StatusScreen dataset={dataset} />}
        </ErrorBoundary>
      </div>
      <ChatBar dataset={dataset} tab={tab} placeholder={chatPlaceholder(dataset)} />
    </div>
  );
}

/** Remember where I was (PRD §7.11): the scroll position per dataset and tab, in this browser. It is
 * restored once the content is tall enough to scroll there (the dashboard's widgets load after it). */
function useRememberScroll(ref: React.RefObject<HTMLDivElement | null>, key: string | null) {
  useEffect(() => {
    const el = ref.current;
    if (!el || !key) return;
    const storeKey = `sherlock.scroll.${key}`;
    let target = 0;
    try { target = Number(localStorage.getItem(storeKey)) || 0; } catch { /* private mode */ }
    let restoring = target > 0;
    const tries = setInterval(() => {
      if (!restoring) return clearInterval(tries);
      if (el.scrollHeight - el.clientHeight >= target) { el.scrollTop = target; restoring = false; }
    }, 150);
    const stop = setTimeout(() => { restoring = false; }, 4000);
    let t: ReturnType<typeof setTimeout> | undefined;
    const onScroll = () => {
      if (restoring) return;
      clearTimeout(t);
      t = setTimeout(() => { try { localStorage.setItem(storeKey, String(Math.round(el.scrollTop))); } catch { /* private mode */ } }, 200);
    };
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => { clearInterval(tries); clearTimeout(stop); clearTimeout(t); el.removeEventListener("scroll", onScroll); };
  }, [ref, key]);
}

/** One event stream per open dataset; the cascade sets the "updating" state and ends with a toast. */
function DatasetEvents({ datasetId }: { datasetId: string }) {
  const setCascade = useUi((s) => s.setCascade);
  useDatasetEvents(datasetId, ({ type, data }) => {
    if (type === "started") {
      setCascade(datasetId, { version: data.version as number, widgetIds: (data.widget_ids as string[]) ?? [], cardIds: (data.card_ids as string[]) ?? [] });
      return;
    }
    setCascade(datasetId, null);
    const c = (data.counts ?? {}) as { widgets?: number; cards?: number };
    const parts = [];
    if (c.widgets) parts.push(`${c.widgets} ${c.widgets === 1 ? "widget" : "widgets"} re-queried`);
    if (c.cards) parts.push(`${c.cards} ${c.cards === 1 ? "story" : "stories"} updated`);
    if (parts.length) toast(`v${data.version}: ${parts.join(", ")}.`);
  });
  return null;
}

/** The cascade's progress line under the header (App Flow §16). */
function CascadeLine({ datasetId }: { datasetId: string }) {
  const c = useUi((s) => s.cascade[datasetId]);
  if (!c) return null;
  const w = c.widgetIds.length;
  const k = c.cardIds.length;
  const parts = [w ? `${w} ${w === 1 ? "widget" : "widgets"}` : "", k ? `${k} ${k === 1 ? "story" : "stories"}` : ""].filter(Boolean);
  return (
    <div className="relative shrink-0 border-b border-border px-6 py-1 text-[12px] text-muted-foreground" role="status">
      <div className="absolute inset-x-0 top-0 h-0.5 animate-pulse bg-accent" aria-hidden />
      Updating {parts.join(" and ") || "the dashboard"}
    </div>
  );
}

/** Opening a tab records it as the dataset's last tab (App Flow §1: `/d/:id` opens it). */
function RememberTab({ datasetId, tab, active }: { datasetId: string; tab: Tab; active: boolean }) {
  useEffect(() => {
    if (active) rememberTab(datasetId, tab);
  }, [datasetId, tab, active]);
  return null;
}

function StatusScreen({ dataset }: { dataset: Dataset }) {
  switch (dataset.status) {
    case "profiling":
      return <ProfilingScreen dataset={dataset} />;
    case "failed":
      return <FailedScreen dataset={dataset} />;
    case "cleaning":
      return <CleaningProgress dataset={dataset} />;
    case "building":
      return <BuildingScreen dataset={dataset} />;
    default:
      return <OfferOrPlan dataset={dataset} />;
  }
}

/** The offer, or the cleaning plan once Clean with AI made one (App Flow §4). */
function OfferOrPlan({ dataset }: { dataset: Dataset }) {
  const creating = useIsMutating({ mutationKey: ["create-plan", dataset.id] }) > 0;
  if (dataset.clean_plan_id || creating) return <CleanPlanPanel dataset={dataset} layout="centre" />;
  return <CleaningOffer dataset={dataset} actions={<OfferActions dataset={dataset} />} />;
}

function TabContent({ dataset, tab }: { dataset: Dataset; tab: Tab }) {
  if (tab === "csv") {
    return (
      <Suspense fallback={<p className="p-6 text-muted-foreground">Loading rows…</p>}>
        <CsvTab dataset={dataset} />
      </Suspense>
    );
  }
  if (tab === "dashboard") {
    return (
      <Suspense fallback={<div role="status" className="m-6 h-[300px] animate-pulse rounded-[16px] border border-border bg-card" aria-label="Loading the dashboard" />}>
        <Dashboard dataset={dataset} />
      </Suspense>
    );
  }
  return (
    <Suspense fallback={<p className="p-6 text-muted-foreground">Loading the canvas…</p>}>
      <FlowTab dataset={dataset} />
    </Suspense>
  );
}

function chatPlaceholder(d: Dataset) {
  if (d.status === "profiling") return "Ask about this CSV (profiling in progress)";
  return "Ask Sherlock, or tell it what to build…";
}
