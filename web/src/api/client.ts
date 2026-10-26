// The API client (TRD §3.1): openapi-fetch over the generated schema, same origin, so the
// sherlock_uid cookie always goes along. Errors come back as the TRD §4 envelope.
import createClient from "openapi-fetch";
import type { paths } from "./schema";

// `fetch` is looked up per call (not captured at load), so tests can stub it.
export const api = createClient<paths>({
  baseUrl: typeof window === "undefined" ? "" : window.location.origin, // absolute, so Request() parses it everywhere
  credentials: "same-origin",
  fetch: (req) => globalThis.fetch(req),
});

export class ApiError extends Error {
  status: number;
  code: string;
  extra: Record<string, unknown>;

  constructor(status: number, code: string, message: string, extra: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.extra = extra;
  }
}

interface Envelope {
  error?: { code?: string; message?: string; [key: string]: unknown };
}

export function toApiError(status: number, body: unknown): ApiError {
  const err = typeof body === "object" && body !== null ? (body as Envelope).error : undefined;
  if (err && typeof err.message === "string") {
    const { code, message, ...extra } = err;
    return new ApiError(status, code ?? "internal", message, extra);
  }
  return withoutEnvelope(status);
}

/** A response without the JSON envelope came from something in front of Sherlock: the host's firewall
 * answers some requests with an HTML 403 page, and its proxy a 502 while a deploy restarts the server.
 * The page is never shown; the status says what happened (UI brief §7: what happened, then what to do). */
function withoutEnvelope(status: number): ApiError {
  if (status === 403) {
    return new ApiError(status, "blocked", "The host's firewall blocked that request before it reached Sherlock. Reword it and try again.");
  }
  if (status === 413) return new ApiError(status, "too_large", "That's too large to send. Try a smaller file or a shorter message.");
  if (status === 429) return new ApiError(status, "rate_limited", "Too many requests at once. Wait a minute and try again.");
  if (status === 502 || status === 503 || status === 504) {
    return new ApiError(status, "unavailable", "Sherlock isn't answering right now, perhaps while it restarts. Try again in a minute.");
  }
  return new ApiError(status, "internal", "Something went wrong on our side.");
}

/** A successful status whose body isn't the JSON the route sends (an HTML page from a proxy). */
export const unreadable = () => new ApiError(502, "unavailable", "Sherlock's answer couldn't be read. Try again in a minute.");

/** A request that couldn't reach the server shows the offline banner (it clears itself). */
function signalOffline() {
  if (typeof window !== "undefined") window.dispatchEvent(new Event("sherlock:offline"));
}

/** Unwraps an openapi-fetch result: the data, or throws the envelope as an ApiError. */
export async function unwrap<T>(p: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  let result;
  try {
    result = await p;
  } catch (e) {
    if (e instanceof SyntaxError) throw unreadable(); // openapi-fetch parses a 200's body as JSON
    signalOffline();
    throw new ApiError(0, "offline", "Couldn't reach Sherlock. Check your connection and try again.");
  }
  if (result.error !== undefined || !result.response.ok) throw toApiError(result.response.status, result.error);
  return result.data as T;
}

/** A plain request for routes whose response the schema doesn't type (or multipart bodies). */
export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, credentials: "same-origin" };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers = { "Content-Type": "application/json" };
  }
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    signalOffline();
    throw new ApiError(0, "offline", "Couldn't reach Sherlock. Check your connection and try again.");
  }
  if (response.status === 204) return undefined as T;
  const text = await response.text().catch(() => "");
  let data: unknown;
  try {
    data = text ? JSON.parse(text) : undefined;
  } catch {
    if (response.ok) throw unreadable();
  }
  if (!response.ok) throw toApiError(response.status, data);
  return data as T;
}
