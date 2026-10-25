// TanStack Query hooks over the API, and the user-level event stream that keeps the library live.
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api, request, unwrap } from "./client";
import { useEventStream } from "./sse";
import type {
  CleaningReport, DataCard, Dataset, DatasetStatusEvent, Job, JobProgressEvent, Me, Settings, Step,
} from "./types";

export const keys = {
  me: ["me"] as const,
  datasets: ["datasets"] as const,
  dataset: (id: string) => ["datasets", id] as const,
  datacard: (id: string, version?: number) => ["datacard", id, version ?? "current"] as const,
  jobs: (id: string) => ["jobs", id] as const,
  steps: (id: string) => ["steps", id] as const,
  report: (id: string, jobId?: string) => ["report", id, jobId ?? "latest"] as const,
};

export function useMe() {
  return useQuery({ queryKey: keys.me, queryFn: () => unwrap(api.GET("/api/v1/me")) as Promise<Me> });
}

export function useSaveSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (patch: Partial<Settings>) =>
      unwrap(api.PUT("/api/v1/me/settings", { body: patch as Settings })) as Promise<Settings>,
    onMutate: (patch) => {
      const me = qc.getQueryData<Me>(keys.me);
      if (me) qc.setQueryData<Me>(keys.me, { ...me, settings: { ...me.settings, ...patch } });
    },
    onSuccess: (settings) => {
      const me = qc.getQueryData<Me>(keys.me);
      if (me) qc.setQueryData<Me>(keys.me, { ...me, settings });
    },
  });
}

export function useDatasets() {
  return useQuery({
    queryKey: keys.datasets,
    queryFn: () => unwrap(api.GET("/api/v1/datasets")) as Promise<Dataset[]>,
  });
}

/** Opening a dataset records last_opened_at on the server (TRD §4.2). */
export function useDataset(id: string | undefined) {
  return useQuery({
    queryKey: keys.dataset(id ?? ""),
    enabled: !!id,
    queryFn: () =>
      unwrap(api.GET("/api/v1/datasets/{dataset_id}", { params: { path: { dataset_id: id! } } })) as Promise<Dataset>,
    retry: (count, err) => (err as { status?: number }).status !== 404 && count < 2,
  });
}

export function useDatacard(id: string | undefined, enabled = true) {
  return useQuery({
    queryKey: keys.datacard(id ?? ""),
    enabled: !!id && enabled,
    queryFn: () => request<DataCard>("GET", `/api/v1/datasets/${id}/datacard`),
  });
}

export function useJobs(datasetId: string | undefined) {
  return useQuery({
    queryKey: keys.jobs(datasetId ?? ""),
    enabled: !!datasetId,
    queryFn: () => request<Job[]>("GET", `/api/v1/jobs?dataset_id=${datasetId}`),
  });
}

export function useSteps(datasetId: string | undefined) {
  return useQuery({
    queryKey: keys.steps(datasetId ?? ""),
    enabled: !!datasetId,
    queryFn: () => request<Step[]>("GET", `/api/v1/datasets/${datasetId}/steps`),
  });
}

export function useReport(datasetId: string | undefined, jobId?: string, enabled = true) {
  return useQuery({
    queryKey: keys.report(datasetId ?? "", jobId),
    enabled: !!datasetId && enabled,
    queryFn: () =>
      request<CleaningReport>("GET", `/api/v1/datasets/${datasetId}/report${jobId ? `?job_id=${jobId}` : ""}`),
    retry: false,
  });
}

export interface ImportOptions {
  delimiter?: string;
  encoding?: string;
  header_row?: number;
  skip_rows?: number;
}

function upsertDataset(qc: QueryClient, ds: Dataset) {
  qc.setQueryData<Dataset[]>(keys.datasets, (list) => [ds, ...(list ?? []).filter((d) => d.id !== ds.id)]);
  qc.setQueryData(keys.dataset(ds.id), ds);
  // The profile job can finish before this response arrives, so its dataset.status event may
  // already have been applied to nothing: read the dataset again rather than trust this copy.
  qc.invalidateQueries({ queryKey: keys.dataset(ds.id) });
  qc.invalidateQueries({ queryKey: keys.datasets, exact: true });
}

export function useUpload() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ file, options }: { file: File; options?: ImportOptions }) => {
      const form = new FormData();
      form.append("file", file, file.name);
      if (options && Object.keys(options).length) form.append("options", JSON.stringify(options));
      return request<Dataset>("POST", "/api/v1/datasets", form);
    },
    onSuccess: (ds) => upsertDataset(qc, ds),
  });
}

export function useSample() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/datasets/sample")) as Promise<Dataset>,
    onSuccess: (ds) => upsertDataset(qc, ds),
  });
}

export function useStartCleaning(datasetId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      request<Job>("POST", `/api/v1/datasets/${datasetId}/clean`, {
        mode: "auto", scope: { kind: "all" }, include_user_edited: false,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.jobs(datasetId) });
      qc.invalidateQueries({ queryKey: keys.dataset(datasetId) });
    },
  });
}

export function useUseAsIs(datasetId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => request<Job>("POST", `/api/v1/datasets/${datasetId}/use-as-is`),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.dataset(datasetId) }),
  });
}

export function useCancelJob(datasetId?: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => request<void>("POST", `/api/v1/jobs/${jobId}/cancel`),
    onSuccess: () => datasetId && qc.invalidateQueries({ queryKey: keys.jobs(datasetId) }),
  });
}

/** Live progress per dataset from the user-level stream (`job.progress`). */
export type ProgressMap = Record<string, JobProgressEvent>;

export function applyStatus(qc: QueryClient, e: DatasetStatusEvent) {
  const patch = (d: Dataset): Dataset =>
    d.id === e.dataset_id
      ? { ...d, status: e.status, current_version: e.current_version, error: e.error ?? null }
      : d;
  qc.setQueryData<Dataset[]>(keys.datasets, (list) => list?.map(patch));
  qc.setQueryData<Dataset>(keys.dataset(e.dataset_id), (d) => (d ? patch(d) : d));
  qc.invalidateQueries({ queryKey: ["datacard", e.dataset_id] });
  qc.invalidateQueries({ queryKey: keys.jobs(e.dataset_id) });
  // A status change can mean a new dataset row count (after typing or cleaning).
  qc.invalidateQueries({ queryKey: keys.datasets });
}

/** The user-level stream (GET /events): dataset.status and job.progress for the whole library. */
export function useLibraryEvents(onProgress: (e: JobProgressEvent) => void) {
  const qc = useQueryClient();
  useEventStream("/api/v1/events", {
    "dataset.status": (data) => applyStatus(qc, data as DatasetStatusEvent),
    "job.progress": (data) => onProgress(data as JobProgressEvent),
  });
}
