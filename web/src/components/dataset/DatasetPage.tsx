// A dataset route (App Flow §1): `/d/:id/:tab`. Until the dataset is ready, the centre shows the
// status screen for where it is (profiling, offer, cleaning, building, failed).
import { useEffect } from "react";
import { Navigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { useDataset, useMe } from "@/api/queries";
import type { Dataset, Tab } from "@/api/types";
import { CenterHeader } from "@/components/shell/CenterHeader";
import { ChatBar } from "@/components/shell/ChatBar";
import { CleaningOffer } from "./CleaningOffer";
import { CleaningProgress } from "./CleaningProgress";
import { ReportSummary } from "./CleaningReport";
import { OfferActions } from "./OfferActions";
import { RowsTable } from "./RowsTable";
import { BuildingScreen, FailedScreen, ProfilingScreen } from "./StatusScreens";

const TABS: Tab[] = ["csv", "dashboard", "flow"];

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
  return (
    <div className="flex h-full min-h-0 flex-col">
      <CenterHeader dataset={dataset} tab={tab} enabled={enabled} />
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
        {showTab ? <TabContent dataset={dataset} tab={tab} /> : <StatusScreen dataset={dataset} />}
      </div>
      <ChatBar placeholder={chatPlaceholder(dataset)} />
    </div>
  );
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
      return <CleaningOffer dataset={dataset} actions={<OfferActions dataset={dataset} />} />;
  }
}

function TabContent({ dataset, tab }: { dataset: Dataset; tab: Tab }) {
  if (tab === "csv") return <RowsTable datasetId={dataset.id} version={dataset.current_version} />;
  return (
    <div className="mx-auto flex w-full max-w-[640px] flex-1 flex-col gap-6 p-8">
      <div className="flex flex-col items-center gap-2 text-center">
        <h2 className="text-[15px] font-semibold">{tab === "dashboard" ? "No widgets yet" : "The canvas is empty"}</h2>
        <p className="text-muted-foreground">
          {tab === "dashboard"
            ? "Widgets appear here once the dashboard builds."
            : "Cards and notes you place on the canvas appear here."}
        </p>
      </div>
      {tab === "dashboard" && <ReportSummary datasetId={dataset.id} title="Last cleaning report" />}
    </div>
  );
}

function chatPlaceholder(d: Dataset) {
  if (d.status === "profiling") return "Ask about this CSV (profiling in progress)";
  return "Ask Sherlock, or tell it what to build…";
}
