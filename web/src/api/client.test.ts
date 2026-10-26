// Responses that aren't Sherlock's JSON (live test finding 22): the host's firewall answers some requests
// with an HTML 403 page, and its proxy with a 502 page while a deploy restarts. The user gets a plain
// sentence, never the page or a JSON parse error.
import { afterEach, describe, expect, it, vi } from "vitest";
import { api, request, toApiError, unwrap } from "./client";

afterEach(() => vi.unstubAllGlobals());

const html = (status: number) => vi.fn(async () =>
  new Response("<!doctype html><title>403 Forbidden</title>", { status, headers: { "Content-Type": "text/html" } }));

describe("a response without the JSON envelope", () => {
  it("says a firewall 403 blocked the request", async () => {
    vi.stubGlobal("fetch", html(403));
    await expect(request("GET", "/api/v1/datasets/ds_1/find?q=x")).rejects.toMatchObject({
      status: 403, code: "blocked", message: expect.stringContaining("firewall blocked that request"),
    });
  });

  it("says Sherlock isn't answering on a gateway error", () => {
    expect(toApiError(502, "<html>Bad gateway</html>")).toMatchObject({ code: "unavailable" });
  });

  it("keeps the server's own message when the envelope is there", () => {
    expect(toApiError(403, { error: { code: "forbidden", message: "Not yours." } }).message).toBe("Not yours.");
  });

  it("reads an HTML page on a 200 as unreadable, not as being offline", async () => {
    vi.stubGlobal("fetch", html(200));
    await expect(request("GET", "/api/v1/me")).rejects.toMatchObject({ code: "unavailable" });
    await expect(unwrap(api.GET("/api/v1/me"))).rejects.toMatchObject({ code: "unavailable" });
  });
});
