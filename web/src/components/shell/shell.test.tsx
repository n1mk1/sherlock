import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EMPTY_THREAD_HINT } from "./ChatBar";
import { ErrorBoundary } from "./ErrorBoundary";
import { OfflineBanner } from "./OfflineBanner";

function Boom(): never {
  throw new Error("kaboom");
}

describe("quality of life (D8.3)", () => {
  it("contains a crash to its view and offers Try again", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(<ErrorBoundary label="dashboard"><Boom /></ErrorBoundary>);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Something went wrong showing the dashboard");
    expect(alert).toHaveTextContent("kaboom");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("shows the offline banner when a request can't reach the server", () => {
    render(<OfflineBanner />);
    expect(screen.queryByRole("status")).toBeNull();
    act(() => { window.dispatchEvent(new Event("sherlock:offline")); });
    expect(screen.getByRole("status")).toHaveTextContent("Can't reach Sherlock");
    act(() => { window.dispatchEvent(new Event("online")); });
    expect(screen.queryByRole("status")).toBeNull();
    fireEvent(window, new Event("offline"));
    expect(screen.getByRole("status")).toBeInTheDocument();
  });
});

describe("the empty chat thread's hint (Day 9 review)", () => {
  it("names no sample column, so it fits any file (CLAUDE.md rule 4)", () => {
    expect(EMPTY_THREAD_HINT).not.toMatch(/fare|class|port|surviv|passenger|titanic/i);
  });
});
