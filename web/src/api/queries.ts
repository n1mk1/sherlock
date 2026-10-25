// TanStack Query hooks over the API, and the user-level event stream that keeps the library live.
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api, ApiError, request, toApiError, unwrap } from "./client";
import { useEventStream } from "./sse";
import type {
  CleaningReport, DataCard, Dataset, DatasetStatusEvent, Explain, FilterClause, Job, JobProgressEvent, Layout, Me,
  Message, Settings, Step, Tab, Widget, WidgetData, WidgetSpec,
} from "./types";

export const keys = {
  me: ["me"] as const,
  datasets: ["datasets"] as const,
  dataset: (id: string) => ["datasets", id] as const,
  datacard: (id: string, version?: number) => ["datacard", id, version ?? "current"] as const,
  jobs: (id: string) => ["jobs", id] as const,
  steps: (id: string) => ["steps", id] as const,
  report: (id: string, jobId?: string) => ["report", id, jobId ?? "latest"] as const,
  widgets: (id: string) => ["widgets", id] as const,
  widgetData: (wid: string, filter: string, version: number) => ["widget-data", wid, filter, version] as const,
  explain: (wid: string, filter: string) => ["explain", wid, filter] as const,
  allJobs: ["jobs", "all"] as const,
  chat: (id: string) => ["chat", id] as const,
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
  // Becoming ready means the builder has just made the widgets.
  qc.invalidateQueries({ queryKey: ["widgets", e.dataset_id] });
  // A status change can mean a new dataset row count (after typing or cleaning).
  qc.invalidateQueries({ queryKey: keys.datasets });
}

// --- datasets: rename, delete, restore, last tab (TRD §4.2) ---------------------------------

function patchDatasetCaches(qc: QueryClient, ds: Dataset) {
  qc.setQueryData<Dataset[]>(keys.datasets, (list) => list?.map((d) => (d.id === ds.id ? ds : d)));
  qc.setQueryData(keys.dataset(ds.id), ds);
}

export function useRenameDataset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => request<Dataset>("PATCH", `/api/v1/datasets/${id}`, { name }),
    onSuccess: (ds) => patchDatasetCaches(qc, ds),
  });
}

export function rememberTab(id: string, tab: Tab) {
  return request<Dataset>("PATCH", `/api/v1/datasets/${id}`, { last_tab: tab }).catch(() => undefined);
}

export function useDeleteDataset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => request<void>("DELETE", `/api/v1/datasets/${id}`),
    onSuccess: (_, id) => {
      qc.setQueryData<Dataset[]>(keys.datasets, (list) => list?.filter((d) => d.id !== id));
      qc.removeQueries({ queryKey: keys.dataset(id) });
    },
  });
}

export function useRestoreDataset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => request<Dataset>("POST", `/api/v1/datasets/${id}/restore`),
    onSuccess: (ds) => upsertDataset(qc, ds),
  });
}

// --- jobs tray (App Flow §15) ----------------------------------------------------------------

export function useAllJobs() {
  return useQuery({
    queryKey: keys.allJobs,
    queryFn: () => request<Job[]>("GET", "/api/v1/jobs"),
    refetchInterval: 3000,
  });
}

export function useRetryJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: string) => request<Job>("POST", `/api/v1/jobs/${jobId}/retry`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["jobs"] }),
  });
}

// --- widgets (TRD §4.5) -----------------------------------------------------------------------

export const filterParam = (f: FilterClause | null) => (f ? JSON.stringify({ and: [f] }) : "");

export function useWidgets(datasetId: string) {
  return useQuery({
    queryKey: keys.widgets(datasetId),
    queryFn: () => request<{ widgets: Widget[]; layout: Layout }>("GET", `/api/v1/datasets/${datasetId}/widgets`),
  });
}

export function useWidgetData(widget: Widget, filter: string, version: number) {
  return useQuery({
    queryKey: keys.widgetData(widget.id, filter, version),
    queryFn: () =>
      request<WidgetData>("GET", `/api/v1/widgets/${widget.id}/data${filter ? `?filters=${encodeURIComponent(filter)}` : ""}`),
    placeholderData: (prev) => prev, // keep the old chart while a filter re-queries ("updating")
    retry: false,
  });
}

export function useExplain(widgetId: string | null, filter: string) {
  return useQuery({
    queryKey: keys.explain(widgetId ?? "", filter),
    enabled: !!widgetId,
    queryFn: () =>
      request<Explain>("GET", `/api/v1/widgets/${widgetId}/explain${filter ? `?filters=${encodeURIComponent(filter)}` : ""}`),
  });
}

export function useWidgetActions(datasetId: string) {
  const qc = useQueryClient();
  const refresh = () => qc.invalidateQueries({ queryKey: keys.widgets(datasetId) });
  return {
    create: useMutation({
      mutationFn: (body: (WidgetSpec & { title?: string }) | { prompt: string }) =>
        request<{ widget: Widget; warning?: string }>("POST", `/api/v1/datasets/${datasetId}/widgets`, body),
      onSuccess: refresh,
    }),
    patch: useMutation({
      mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) => request<Widget>("PATCH", `/api/v1/widgets/${id}`, body),
      onSuccess: refresh,
    }),
    remove: useMutation({
      mutationFn: (id: string) => request<void>("DELETE", `/api/v1/widgets/${id}`),
      onSuccess: refresh,
    }),
    restore: useMutation({
      mutationFn: (id: string) => request<Widget>("POST", `/api/v1/widgets/${id}/restore`),
      onSuccess: refresh,
    }),
    duplicate: useMutation({
      mutationFn: (id: string) => request<Widget>("POST", `/api/v1/widgets/${id}/duplicate`),
      onSuccess: refresh,
    }),
    saveLayout: useMutation({
      mutationFn: (layout: Layout) => request<Layout>("PUT", `/api/v1/datasets/${datasetId}/layout`, layout),
      onSuccess: (layout) =>
        qc.setQueryData<{ widgets: Widget[]; layout: Layout }>(keys.widgets(datasetId), (d) => (d ? { ...d, layout } : d)),
    }),
  };
}

/** The dataset stream (GET /datasets/{id}/events): widget and layout changes made elsewhere. */
export function useDashboardEvents(datasetId: string) {
  const qc = useQueryClient();
  useEventStream(`/api/v1/datasets/${datasetId}/events`, {
    "widget.updated": () => qc.invalidateQueries({ queryKey: keys.widgets(datasetId) }),
    "layout.updated": () => qc.invalidateQueries({ queryKey: keys.widgets(datasetId) }),
    "version.created": () => {
      qc.invalidateQueries({ queryKey: keys.widgets(datasetId) });
      qc.invalidateQueries({ queryKey: keys.dataset(datasetId) });
    },
  });
}

// --- chat (TRD §4.9, §5.3) --------------------------------------------------------------------

export function useThread(datasetId: string) {
  return useQuery({
    queryKey: keys.chat(datasetId),
    queryFn: () => request<Message[]>("GET", `/api/v1/datasets/${datasetId}/chat`),
  });
}

export interface ChatEvent {
  type: string;
  data: Record<string, unknown>;
}

/** POST /chat read as a stream of SSE frames with fetch (EventSource can't POST). */
export async function sendChat(datasetId: string, body: Record<string, unknown>, onEvent: (e: ChatEvent) => void) {
  let response: Response;
  try {
    response = await fetch(`/api/v1/datasets/${datasetId}/chat`, {
      method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "offline", "Couldn't reach Sherlock. Check your connection and try again.");
  }
  if (!response.ok || !response.body) {
    throw toApiError(response.status, await response.json().catch(() => undefined));
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut: number;
    while ((cut = buffer.indexOf("\n\n")) >= 0) {
      const frame = buffer.slice(0, cut);
      buffer = buffer.slice(cut + 2);
      let type = "message";
      let data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event: ")) type = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (data) onEvent({ type, data: JSON.parse(data) });
    }
  }
}

export function usePin(datasetId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ messageId, blockIndex }: { messageId: string; blockIndex: number }) =>
      request<Widget>("POST", `/api/v1/messages/${messageId}/pin`, { target: "dashboard", block_index: blockIndex }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.widgets(datasetId) }),
  });
}

/** The user-level stream (GET /events): dataset.status and job.progress for the whole library. */
export function useLibraryEvents(onProgress: (e: JobProgressEvent) => void) {
  const qc = useQueryClient();
  useEventStream("/api/v1/events", {
    "dataset.status": (data) => applyStatus(qc, data as DatasetStatusEvent),
    "job.progress": (data) => onProgress(data as JobProgressEvent),
  });
}
