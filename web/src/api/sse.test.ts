// The event stream catches up (TRD §5.2): a dropped stream reopens from the last id it saw,
// says so (the caller reads its queries again), and handles each event once even out of order.
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useDataset, useDatasetEvents } from "@/api/queries";
import { stubEventSource } from "@/test/eventsource";
import { mockApi } from "@/test/render";
import { openStream } from "./sse";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("openStream", () => {
  it("handles an event that arrives late, and skips one a replay sends again", () => {
    const ES = stubEventSource();
    const got: number[] = [];
    const close = openStream("/api/v1/events", () => ({ "job.progress": (_, id) => got.push(id) }));
    const s = ES.last();
    s.open();
    s.emit("job.progress", {}, 5);
    s.emit("job.progress", {}, 7);
    s.emit("job.progress", {}, 6); // published after 7 by another thread: still new
    s.emit("job.progress", {}, 7); // a replay's copy
    expect(got).toEqual([5, 7, 6]);
    close();
  });

  it("reopens from the last id seen when the browser gives up, and reports each reopen", () => {
    vi.useFakeTimers();
    const ES = stubEventSource();
    const onReopen = vi.fn();
    const close = openStream("/api/v1/events", () => ({ "dataset.status": () => {} }), { onReopen });
    ES.last().open();
    expect(onReopen).not.toHaveBeenCalled(); // the first open isn't a reopen
    ES.last().emit("dataset.status", {}, 9);

    ES.last().drop(true); // the browser reconnects by itself (it sends Last-Event-ID)
    ES.last().open();
    expect(onReopen).toHaveBeenCalledTimes(1);
    expect(ES.instances).toHaveLength(1);

    ES.last().drop(); // it gave up: ours reopens after 1 s with the last id
    vi.advanceTimersByTime(1000);
    expect(ES.instances).toHaveLength(2);
    expect(ES.last().url).toBe("/api/v1/events?last_event_id=9");
    ES.last().open();
    expect(onReopen).toHaveBeenCalledTimes(2);
    close();
  });
});

describe("useDatasetEvents", () => {
  it("reads the dataset again when its stream reopens", async () => {
    const ES = stubEventSource();
    let reads = 0;
    mockApi({
      "GET /api/v1/datasets/ds_1": () => {
        reads += 1;
        return { id: "ds_1", status: "ready", current_version: reads + 1 };
      },
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client: qc }, children);
    const { result } = renderHook(() => {
      useDatasetEvents("ds_1", () => {});
      return useDataset("ds_1");
    }, { wrapper });
    await waitFor(() => expect(result.current.data?.current_version).toBe(2));
    const stream = ES.instances.find((s) => s.url.startsWith("/api/v1/datasets/ds_1/events"))!;
    act(() => stream.open());
    act(() => stream.drop(true)); // the server restarted; a version was made meanwhile
    act(() => stream.open());
    await waitFor(() => expect(result.current.data?.current_version).toBe(3));
    expect(reads).toBe(2);
  });
});
