// A stand-in for the browser's EventSource: tests feed events to the stream the app opened, and
// drop it the way a browser does when the server goes away.
import { vi } from "vitest";

type Listener = (ev: MessageEvent<string>) => void;

export class FakeEventSource {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  static instances: FakeEventSource[] = [];

  readyState = FakeEventSource.CONNECTING;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  private listeners = new Map<string, Listener[]>();

  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }

  /** The stream opened last. */
  static last(): FakeEventSource {
    return FakeEventSource.instances[FakeEventSource.instances.length - 1];
  }

  addEventListener(type: string, fn: Listener) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn]);
  }

  open() {
    this.readyState = FakeEventSource.OPEN;
    this.onopen?.();
  }

  /** One `event:`/`data:`/`id:` frame. */
  emit(type: string, data: unknown, id?: number) {
    const ev = new MessageEvent<string>(type, { data: JSON.stringify(data), lastEventId: id ? String(id) : "" });
    for (const fn of this.listeners.get(type) ?? []) fn(ev);
  }

  /** The connection drops: `reconnecting` is the browser trying again itself, otherwise it gave up. */
  drop(reconnecting = false) {
    this.readyState = reconnecting ? FakeEventSource.CONNECTING : FakeEventSource.CLOSED;
    this.onerror?.();
  }

  close() {
    this.readyState = FakeEventSource.CLOSED;
  }
}

export function stubEventSource() {
  FakeEventSource.instances = [];
  vi.stubGlobal("EventSource", FakeEventSource);
  return FakeEventSource;
}
