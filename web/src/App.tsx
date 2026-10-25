// Routes (App Flow §1). Every route sits inside the three-panel shell.
import { Route, Routes } from "react-router-dom";
import { ThemeSync } from "@/app/ThemeSync";
import { DatasetPage, DatasetRedirect } from "@/components/dataset/DatasetPage";
import { Home } from "@/components/library/Home";
import { AppShell } from "@/components/shell/AppShell";

export function App() {
  return (
    <>
      <ThemeSync />
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<Home />} />
          <Route path="d/:datasetId" element={<DatasetRedirect />} />
          <Route path="d/:datasetId/:tab" element={<DatasetPage />} />
          <Route path="*" element={<Home />} />
        </Route>
      </Routes>
    </>
  );
}
