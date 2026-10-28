// A dataset route (App Flow §1): `/d/:id`, and `/d/:id/:tab` so older links still open it. One view: until
// the dataset is ready, the centre shows the status screen for where it is (profiling, offer, cleaning,
// failed); once it's ready, the CSV grid. The chat bar sits below; the right panel is the cleaning side
// panel (AppShell).
import { useIsMutating } from "@tanstack/react-query";
import { lazy, Suspense, useEffect } from "react";
import { Navigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { useDataset, useDatasetEvents } from "@/api/queries";
import type { Dataset } from "@/api/types";
import { SaveActions } from "@/components/csv/SaveActions";
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
import { FailedScreen, ProfilingScreen } from "./StatusScreens";

// The CSV grid (Glide Data Grid) loads when a ready dataset first opens.
const CsvTab = lazy(() => import("@/components/csv/CsvTab").then((m) => ({ default: m.CsvTab })));

function Gone() {
  useEffect(() => {
    toast("That CSV is no longer available.");
  }, []);
  return <Navigate to="/" replace state={{ stay: true }} />;
}

export function DatasetPage() {
  const { datasetId } = useParams();
  const { data: dataset, error } = useDataset(datasetId);
  if (error) return <Gone />;
  if (!dataset) return null;
  const ready = dataset.status === "ready";
  return (
    <div className="flex h-full min-h-0 flex-col">
      <DatasetEvents datasetId={dataset.id} />
      <ExportDialog dataset={dataset} />
      <CenterHeader
        dataset={dataset}
        actions={
          <>
            {ready && <SaveActions dataset={dataset} />}
            <JobTray />
            <DatasetMenu dataset={dataset} />
          </>
        }
      />
      <div className={ready ? "flex min-h-0 flex-1 flex-col" : "flex min-h-0 flex-1 flex-col overflow-hidden"}>
        <ErrorBoundary label={ready ? "grid" : "CSV"} resetKey={`${dataset.id}:${dataset.status}`}>
          {ready ? (
            <Suspense fallback={<p className="p-6 text-[13px] text-muted-foreground">Loading rows…</p>}>
              <CsvTab dataset={dataset} />
            </Suspense>
          ) : (
            <StatusScreen dataset={dataset} />
          )}
        </ErrorBoundary>
      </div>
      <ChatBar dataset={dataset} placeholder={chatPlaceholder(dataset)} />
    </div>
  );
}

/** One event stream per open dataset (TRD §5.1). */
function DatasetEvents({ datasetId }: { datasetId: string }) {
  useDatasetEvents(datasetId);
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
    default:
      return <OfferOrPlan dataset={dataset} />;
  }
}

/** The offer, or the cleaning plan once Clean with AI made one (App Flow §4). */
function OfferOrPlan({ dataset }: { dataset: Dataset }) {
  const creating = useIsMutating({ mutationKey: ["create-plan", dataset.id] }) > 0;
  if (dataset.clean_plan_id || creating) return <CleanPlanPanel dataset={dataset} layout="centre" />;
  return <CleaningOffer dataset={dataset} actions={(depth) => <OfferActions dataset={dataset} depth={depth} />} />;
}

function chatPlaceholder(d: Dataset) {
  if (d.status === "profiling") return "You can ask once Sherlock has read the file";
  return "Ask anything, or describe a change…";
}
