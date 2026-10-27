// Routes (App Flow §1). Every route sits inside the three-panel shell.
import { Route, Routes } from "react-router-dom";
import { useMe } from "@/api/queries";
import { ThemeSync } from "@/app/ThemeSync";
import { DatasetPage } from "@/components/dataset/DatasetPage";
import { Home } from "@/components/library/Home";
import { AppShell } from "@/components/shell/AppShell";
import { StartupError } from "@/components/shell/StartupError";

export function App() {
  // A first visit has no identity cookie yet: `GET /me` creates the user and sets it. Nothing else asks
  // before that answer, or each of the page's first requests would create its own user, and the
  // library's event stream would listen to a different user than the cookie the browser keeps.
  const me = useMe();
  if (!me.data && !me.isError) return <ThemeSync />;
  if (!me.data) return <StartupError error={me.error} retrying={me.isFetching} onRetry={() => void me.refetch()} />;
  return (
    <>
      <ThemeSync />
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<Home />} />
          <Route path="d/:datasetId" element={<DatasetPage />} />
          {/* The old tab routes (csv, dashboard, flow) open the same view. */}
          <Route path="d/:datasetId/:tab" element={<DatasetPage />} />
          <Route path="*" element={<Home />} />
        </Route>
      </Routes>
    </>
  );
}
