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
  const err = (body as Envelope | undefined)?.error;
  if (err && typeof err.message === "string") {
    const { code, message, ...extra } = err;
    return new ApiError(status, code ?? "internal", message, extra);
  }
  return new ApiError(status, "internal", "Something went wrong on our side.");
}

/** Unwraps an openapi-fetch result: the data, or throws the envelope as an ApiError. */
export async function unwrap<T>(p: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  let result;
  try {
    result = await p;
  } catch {
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
    throw new ApiError(0, "offline", "Couldn't reach Sherlock. Check your connection and try again.");
  }
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => undefined);
  if (!response.ok) throw toApiError(response.status, data);
  return data as T;
}
