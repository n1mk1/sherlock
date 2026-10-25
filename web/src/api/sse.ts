// SSE with resume (TRD §5.2). EventSource resends Last-Event-ID itself when it reconnects; when the
// browser gives up (the stream closed), we reopen with ?last_event_id= and back off up to 30 s.
import { useEffect, useRef } from "react";

export type Handlers = Record<string, (data: unknown, id: number) => void>;

/** `lastEventId` replays the events after it (0 = from the start); without it the stream is live only. */
export function openStream(url: string, handlers: () => Handlers, opts: { lastEventId?: number } = {}) {
  let last = opts.lastEventId ?? -1;
  let source: EventSource | null = null;
  let retry: ReturnType<typeof setTimeout> | null = null;
  let delay = 1000;
  let closed = false;

  const connect = () => {
    const sep = url.includes("?") ? "&" : "?";
    source = new EventSource(last >= 0 ? `${url}${sep}last_event_id=${last}` : url, { withCredentials: true });
    source.onopen = () => {
      delay = 1000;
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
        if (id && id <= last) return; // already seen (a replay after resume)
        if (id) last = id;
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

/** Keeps one stream open while `url` is set; handlers may change between renders. */
export function useEventStream(url: string | null, handlers: Handlers, lastEventId?: number) {
  const ref = useRef(handlers);
  ref.current = handlers;
  const types = Object.keys(handlers).sort().join(",");
  useEffect(() => {
    if (!url || typeof EventSource === "undefined") return;
    return openStream(url, () => ref.current, { lastEventId });
    // The handler set's event types decide the listeners; their bodies are read through the ref.
  }, [url, types, lastEventId]);
}
