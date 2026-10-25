// `/` (App Flow §1): the library; a returning visit goes to the last opened dataset.
import { Navigate, useLocation } from "react-router-dom";
import { useDatasets } from "@/api/queries";
import { EmptyLibrary } from "./EmptyLibrary";

export function Home() {
  const { data: datasets, isLoading } = useDatasets();
  const location = useLocation();
  const stay = (location.state as { stay?: boolean } | null)?.stay;
  if (isLoading) return null;
  const last = datasets?.find((d) => d.last_opened_at);
  if (last && !stay) return <Navigate to={`/d/${last.id}`} replace />;
  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto">
      <EmptyLibrary />
    </div>
  );
}
