// TanStack Query hooks over the API, and the user-level event stream that keeps the library live.
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { api, ApiError, request, toApiError, unreadable, unwrap } from "./client";
import { useEventStream } from "./sse";
import type {
  CleaningReport, CleanPlan, DataCard, Dataset, Depth, Detector, RuleIn, DatasetStatusEvent, Issue, Job,
  JobProgressEvent, Me, Message, PlanOp, Settings, Step,
} from "./types";

export const keys = {
  me: ["me"] as const,
  detectors: ["detectors"] as const,
  datasets: ["datasets"] as const,
  dataset: (id: string) => ["datasets", id] as const,
  datacard: (id: string, version?: number) => ["datacard", id, version ?? "current"] as const,
  jobs: (id: string) => ["jobs", id] as const,
  steps: (id: string) => ["steps", id] as const,
  history: (id: string) => ["history", id] as const,
  report: (id: string, jobId?: string) => ["report", id, jobId ?? "latest"] as const,
  allJobs: ["jobs", "all"] as const,
  chat: (id: string) => ["chat", id] as const,
  plan: (pid: string) => ["clean-plan", pid] as const,
};

export function useMe() {
  return useQuery({
    queryKey: keys.me,
    queryFn: () => unwrap(api.GET("/api/v1/me")) as Promise<Me>,
    // The new-visitor cap won't lift within the retries, so its screen shows at once.
    retry: (count, err) => !(err instanceof ApiError && err.status === 429) && count < 3,
  });
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

/** A dataset's current version from the cache, without reading the dataset again (its page keeps it
 * fresh, and a read records `last_opened_at`). */
export function useCurrentVersion(id: string): number | undefined {
  return useQuery({
    queryKey: keys.dataset(id),
    enabled: false,
    queryFn: () => unwrap(api.GET("/api/v1/datasets/{dataset_id}", { params: { path: { dataset_id: id } } })) as Promise<Dataset>,
  }).data?.current_version;
}

// The detector catalog (PRD CLEAN-12): fixed while the server runs, so it is fetched once.
export function useDetectors() {
  return useQuery({
    queryKey: keys.detectors,
    queryFn: () => unwrap(api.GET("/api/v1/detectors")) as Promise<{ detectors: Detector[] }>,
    staleTime: Infinity,
  });
}

// A detector's plain words from the catalog ("placeholder values"); a user's step is "your step", and
// an id the catalog doesn't list (or before it loads) is shown in words ("unit mixes").
export function useDetectorLabel(): (detector: string) => string {
  const { data } = useDetectors();
  return useCallback((detector: string) => {
    if (detector === "user_request") return "your step";
    const id = detector.split(":")[0]; // a rule's finding, "rule:rul_…", is the rule detector's
    return data?.detectors.find((d) => d.id === id)?.label ?? id.replace(/_/g, " ");
  }, [data]);
}

// The layer a finding belongs to, 1–5 (PRD CLEAN-15): its own `details.depth` (a rule's), else its
// detector's from the catalog; a detector the catalog doesn't list (or before it loads) is layer 1, as the
// server's unknown-detector spec is.
export function useDetectorDepth(): (issue: Pick<Issue, "detector" | "details">) => number {
  const { data } = useDetectors();
  return useCallback((issue: Pick<Issue, "detector" | "details">) => {
    const own = issue.details?.depth;
    if (typeof own === "number") return own;
    const id = issue.detector.split(":")[0];
    return data?.detectors.find((d) => d.id === id)?.depth ?? 1;
  }, [data]);
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

export type CleanScope = { kind: "all" | "selection" | "new_rows"; selection_id?: string; row_ids?: number[] };

/** Start Clean with AI from a cleaning plan (PRD CLEAN-8a). A plan made on an older version answers
 * 409 with the merged plan: the cache takes it and the error says so (`stalePlan`). */
export function useStartCleaning(datasetId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ plan_id, scope }: { plan_id: string; scope?: CleanScope }) =>
      request<Job>("POST", `/api/v1/datasets/${datasetId}/clean`, {
        mode: "auto", scope: scope ?? { kind: "all" }, include_user_edited: false, plan_id,
      }),
    onSuccess: (_, { plan_id }) => {
      setDatasetPlan(qc, datasetId, null);
      qc.invalidateQueries({ queryKey: keys.plan(plan_id) });
      qc.invalidateQueries({ queryKey: keys.jobs(datasetId) });
      qc.invalidateQueries({ queryKey: keys.dataset(datasetId) });
      qc.invalidateQueries({ queryKey: keys.allJobs });
    },
    onError: (err) => {
      const plan = stalePlan(err);
      if (plan) qc.setQueryData(keys.plan(plan.id), plan);
    },
  });
}

export function stalePlan(err: unknown): CleanPlan | null {
  const e = err as ApiError;
  return e?.status === 409 && e.extra?.plan ? (e.extra.plan as CleanPlan) : null;
}

// --- the cleaning plan (TRD §4.4, PRD CLEAN-8a) ------------------------------------------------

function setDatasetPlan(qc: QueryClient, datasetId: string, planId: string | null) {
  const patch = (d: Dataset): Dataset => (d.id === datasetId ? { ...d, clean_plan_id: planId } : d);
  qc.setQueryData<Dataset>(keys.dataset(datasetId), (d) => (d ? patch(d) : d));
  qc.setQueryData<Dataset[]>(keys.datasets, (list) => list?.map(patch));
}

/** Ops applied locally as the server applies them (`cleaning/plan.py` `apply_ops`), shown until its
 * answer arrives. An added step waits for the server, which gives it its ID. */
export function applyPlanOps(plan: CleanPlan, ops: PlanOp[]): CleanPlan {
  let items = plan.items.map((i) => ({ ...i }));
  for (const op of ops) {
    if ("module" in op) {
      for (const i of items) if (i.module === op.module && i.change) i.ticked = op.op === "tick_module";
    } else if ("rule_id" in op) {
      continue; // a suggestion kept or dismissed: the server's plan follows
    } else if ("level" in op) {
      for (const i of items) if (i.sev === op.level && i.change && i.key) i.ticked = op.op === "tick_level";
    } else if ("item_id" in op) {
      const i = items.find((x) => x.id === op.item_id);
      if (!i?.change) continue;
      if ("instruction" in op) {
        i.instruction = op.instruction;
        if (i.key === null && op.instruction) i.action = op.instruction;
      } else if (op.op === "remove" && i.key === null) items = items.filter((x) => x.id !== i.id);
      else i.ticked = op.op === "tick";
    }
  }
  return { ...plan, items };
}

export function useCleanPlan(planId: string | null | undefined) {
  return useQuery({
    queryKey: keys.plan(planId ?? ""),
    enabled: !!planId,
    queryFn: () => request<CleanPlan>("GET", `/api/v1/clean-plans/${planId}`),
    // While the severity review runs, read the plan again every few seconds as well as on `plan.updated`:
    // a review can end before this tab's event stream is listening.
    refetchInterval: (q) => (q.state.data?.review === "running" ? 3000 : false),
  });
}

/** Clean with AI: the dataset's draft plan, made from the current version's diagnosis (or the one
 * already open). With a scope (the new-rows toast's "Clean them"), the plan is for those rows. Its
 * pending state is the "Diagnosing…" screen (`mutationKey`). */
export function useCreatePlan(datasetId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationKey: ["create-plan", datasetId],
    // `depth`: the layers it lists (the offer's slider, PRD CLEAN-15); left out, a new plan takes the
    // user's Cleaning depth setting and a draft keeps its own.
    mutationFn: (opts?: { scope?: CleanScope; depth?: Depth }) =>
      request<CleanPlan>("POST", `/api/v1/datasets/${datasetId}/clean/plan`, opts?.scope || opts?.depth ? opts : undefined),
    onSuccess: (plan) => showPlan(qc, datasetId, plan),
  });
}

/** Put a plan the server answered with on screen: the right panel shows a ready dataset's draft. */
export function showPlan(qc: QueryClient, datasetId: string, plan: CleanPlan) {
  qc.setQueryData(keys.plan(plan.id), plan);
  setDatasetPlan(qc, datasetId, plan.id);
}

/** Ticks and unticks, shown at once and replaced by the server's plan. */
export function usePlanOps(plan: CleanPlan) {
  const qc = useQueryClient();
  const key = keys.plan(plan.id);
  return useMutation({
    mutationFn: (ops: PlanOp[]) => request<CleanPlan>("PATCH", `/api/v1/clean-plans/${plan.id}`, { ops }),
    onMutate: async (ops) => {
      await qc.cancelQueries({ queryKey: key });
      const before = qc.getQueryData<CleanPlan>(key);
      if (before) qc.setQueryData(key, applyPlanOps(before, ops));
      return { before };
    },
    onError: (_, __, ctx) => {
      if (ctx?.before) qc.setQueryData(key, ctx.before);
    },
    onSuccess: (next) => qc.setQueryData(key, next),
  });
}

/** Turn one of your checks off (or on again): the plan is merged on the server and read again. */
export function useRuleStatus(planId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ ruleId, status }: { ruleId: string; status: "active" | "off" }) =>
      request<unknown>("PATCH", `/api/v1/rules/${ruleId}`, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.plan(planId) }),
  });
}

/** Change a check's values or action (a suggestion before it's kept, PRD CLEAN-14); the plan is read again. */
export function useEditRule(planId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ ruleId, params, action }: { ruleId: string; params: Record<string, unknown>; action: RuleIn["action"] }) =>
      request<unknown>("PATCH", `/api/v1/rules/${ruleId}`, { params, action }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.plan(planId) }),
  });
}

/** Discard: the offer (or the Changes panel) shows again. */
export function useDiscardPlan(datasetId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (planId: string) => request<void>("DELETE", `/api/v1/clean-plans/${planId}`),
    onSuccess: (_, planId) => {
      setDatasetPlan(qc, datasetId, null);
      qc.removeQueries({ queryKey: keys.plan(planId) });
      qc.invalidateQueries({ queryKey: keys.dataset(datasetId) });
    },
  });
}

/** Clean it myself (App Flow §4): the dataset is ready at once, as it is. */
export function useUseAsIs(datasetId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => request<Dataset>("POST", `/api/v1/datasets/${datasetId}/use-as-is`),
    onSuccess: (ds) => patchDatasetCaches(qc, ds),
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
  // A status change also ends a clean: its steps and its report.
  qc.invalidateQueries({ queryKey: keys.steps(e.dataset_id) });
  qc.invalidateQueries({ queryKey: ["report", e.dataset_id] });
  // A status change can mean a new dataset row count (after typing or cleaning).
  qc.invalidateQueries({ queryKey: keys.datasets });
}

// --- datasets: rename, delete, restore (TRD §4.2) -------------------------------------------

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

/** The dataset stream (GET /datasets/{id}/events), one per open dataset: new versions refresh the
 * dataset, its steps, rows, data card and analyses (a new version can outdate a run, PRD ML-9). */
export function useDatasetEvents(datasetId: string) {
  const qc = useQueryClient();
  // A reopened stream may have missed any event (TRD §5.2): every query on screen is read again.
  const onReopen = () => qc.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "me" });
  useEventStream(`/api/v1/datasets/${datasetId}/events`, {
    "version.created": () => {
      qc.invalidateQueries({ queryKey: keys.dataset(datasetId) });
      qc.invalidateQueries({ queryKey: keys.datasets, exact: true }); // the library row's "v3"
      qc.invalidateQueries({ queryKey: keys.steps(datasetId) });
      qc.invalidateQueries({ queryKey: keys.history(datasetId) });
      qc.invalidateQueries({ queryKey: ["datacard", datasetId] });
      qc.invalidateQueries({ queryKey: keys.jobs(datasetId) });
      // An open cleaning plan was made on the version before: read again, it's merged onto this one.
      qc.invalidateQueries({ queryKey: ["clean-plan"] });
      // The new version may have outdated a finished run: its model card reads it again.
      qc.invalidateQueries({ queryKey: ["run"] });
      qc.invalidateQueries({ queryKey: ["model-card"] });
    },
    // A message was answered in another tab (or this one): the thread is read again.
    "chat.updated": () => qc.invalidateQueries({ queryKey: keys.chat(datasetId) }),
    // A cleaning plan was made, changed (in another tab, or by chat), started or discarded.
    "plan.updated": (data) => {
      qc.invalidateQueries({ queryKey: keys.plan(String((data as { plan_id?: string }).plan_id)) });
      qc.invalidateQueries({ queryKey: keys.dataset(datasetId) });
    },
    // A run's status (TRD §5): its model card re-reads the run; ML progress refreshes the running ones.
    "run.updated": (data) => {
      const run = data as { id: string };
      qc.invalidateQueries({ queryKey: ["run", run.id] });
      qc.invalidateQueries({ queryKey: ["model-card", run.id] });
    },
    "job.progress": (data) => {
      if ((data as { kind?: string }).kind === "ml_run") qc.invalidateQueries({ queryKey: ["run"] });
    },
  }, undefined, onReopen);
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
  // A 200 that isn't the event stream (an HTML page from a proxy) would otherwise end with no answer.
  if (!(response.headers.get("Content-Type") ?? "").includes("text/event-stream")) throw unreadable();
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

/** The user-level stream (GET /events): dataset.status and job.progress for the whole library. */
export function useLibraryEvents(onProgress: (e: JobProgressEvent) => void) {
  const qc = useQueryClient();
  useEventStream("/api/v1/events", {
    "dataset.status": (data) => applyStatus(qc, data as DatasetStatusEvent),
    "job.progress": (data) => onProgress(data as JobProgressEvent),
  }, undefined, () => {
    // Reopened: a dataset.status may have been missed, so the library and its jobs are read again.
    qc.invalidateQueries({ queryKey: keys.datasets });
    qc.invalidateQueries({ queryKey: ["jobs"] });
  });
}
