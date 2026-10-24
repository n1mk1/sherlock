import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

afterEach(() => vi.unstubAllGlobals());

describe("App", () => {
  it("shows the API version from /healthz", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, version: "0.1.0" }) }),
    );
    render(<App />);
    expect(screen.getByRole("heading", { name: "Sherlock" })).toBeInTheDocument();
    expect(await screen.findByText("API 0.1.0 is up")).toBeInTheDocument();
  });

  it("says when the API is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("down")));
    render(<App />);
    expect(await screen.findByText("API unreachable")).toBeInTheDocument();
  });
});
