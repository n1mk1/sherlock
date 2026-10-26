// SSE with resume (TRD §5.2). A stream opens with an `id:` line (the newest event id), so when the browser
// reconnects by itself it sends Last-Event-ID and the server replays what it missed. When the browser gives
// up (the stream closed), we reopen with ?last_event_id= and back off up to 30 s. Either way `onReopen` runs
// once the stream is back: a replay is capped and a stream that saw no event reopens live-only, so the
// caller reads its queries again rather than trust that nothing was missed.
import { useEffect, useRef } from "react";

export type Handlers = Record<string, (data: unknown, id: number) => void>;

/** Event ids remembered, to skip one handled already when a replay resends it. */
const SEEN = 2000;

/** `lastEventId` replays the events after it (0 = from the start); without it the stream is live only. */
export function openStream(url: string, handlers: () => Handlers, opts: { lastEventId?: number; onReopen?: () => void } = {}) {
  let last = opts.lastEventId ?? -1;
  // Ids handled, not just the highest: events from different threads can arrive out of order, and an
  // older one that arrives after a newer one is still new.
  const seen = new Set<number>();
  let source: EventSource | null = null;
  let retry: ReturnType<typeof setTimeout> | null = null;
  let delay = 1000;
  let closed = false;
  let opened = false;

  const connect = () => {
    const sep = url.includes("?") ? "&" : "?";
    source = new EventSource(last >= 0 ? `${url}${sep}last_event_id=${last}` : url, { withCredentials: true });
    source.onopen = () => {
      delay = 1000;
      if (opened) opts.onReopen?.(); // the browser's own reconnect, or ours
      opened = true;
    };
    source.onerror = () => {
      if (closed || !source || source.readyState !== EventSource.CLOSED) return;
      retry = setTimeout(connect, delay);
      delay = Math.min(delay * 2, 30000);
    };
    for (const type of Object.keys(handlers())) {
      source.addEventListener(type, (ev) => {
        const message = ev as MessageEvent<string>;
        const id = Number(message.lastEventId) || 0;
        if (id) {
          if (seen.has(id)) return; // already handled (a replay after resume)
          seen.add(id);
          if (seen.size > SEEN) seen.delete(seen.values().next().value!);
          last = Math.max(last, id);
        }
        let data: unknown;
        try {
          data = JSON.parse(message.data);
        } catch {
          return;
        }
        handlers()[type]?.(data, id);
      });
    }
  };
  connect();
  return () => {
    closed = true;
    if (retry) clearTimeout(retry);
    source?.close();
  };
}

/** Keeps one stream open while `url` is set; handlers and `onReopen` may change between renders. */
export function useEventStream(url: string | null, handlers: Handlers, lastEventId?: number, onReopen?: () => void) {
  const ref = useRef(handlers);
  ref.current = handlers;
  const reopen = useRef(onReopen);
  reopen.current = onReopen;
  const types = Object.keys(handlers).sort().join(",");
  useEffect(() => {
    if (!url || typeof EventSource === "undefined") return;
    return openStream(url, () => ref.current, { lastEventId, onReopen: () => reopen.current?.() });
    // The handler set's event types decide the listeners; their bodies are read through the ref.
  }, [url, types, lastEventId]);
}
