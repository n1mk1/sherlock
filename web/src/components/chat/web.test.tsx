import { fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AnswerBlock } from "@/api/types";
import { BlockView } from "@/components/chat/Blocks";
import { Sources } from "@/components/shell/ChatBar";
import { renderAt } from "@/test/render";

afterEach(() => vi.unstubAllGlobals());

const WEB: AnswerBlock = {
  type: "text", labeled: "web",
  body: { blocks: [{ type: "paragraph", runs: [
    { type: "text", text: "From the web (not from your data): " },
    { type: "text", text: "A status code records where a parcel is." },
    { type: "cite", n: 1, url: "https://glossary.example.org/status", title: "Glossary" },
  ] }] },
};
const SOURCES: AnswerBlock = {
  type: "web_sources", query: "shipping status code meaning", cached: false,
  results: [{ n: 1, title: "Glossary", url: "https://glossary.example.org/status", domain: "glossary.example.org",
              snippet: "code 7 means returned to sender", retrieved_at: "2026-10-26" }],
};

describe("answers from the web (TRD §8.2 web_context)", () => {
  it("shows cited text, then the search and its quoted sources", () => {
    renderAt(<><BlockView block={WEB} datasetId="ds" /><BlockView block={SOURCES} datasetId="ds" /></>);
    const cite = screen.getByRole("link", { name: "[1]" });
    expect(cite).toHaveAttribute("href", "https://glossary.example.org/status");
    expect(cite).toHaveAttribute("target", "_blank");
    expect(screen.getByText("From the web (not from your data):", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("Searched the web for:", { exact: false })).toHaveTextContent("“shipping status code meaning”");
    fireEvent.click(screen.getByText("1 source"));
    expect(screen.getByRole("link", { name: "Glossary" })).toHaveAttribute("href", "https://glossary.example.org/status");
    expect(screen.getByText("code 7 means returned to sender")).toBeInTheDocument(); // the web's number stays in the quote
  });

  it("links a web source in How do you know?", () => {
    renderAt(<Sources messageId="msg_w" sources={[{ kind: "web", url: "https://glossary.example.org/status", title: "Glossary",
      label: "[1] Glossary (glossary.example.org), retrieved 2026-10-26: from the web, not from your data" }]} />);
    expect(screen.getByRole("link", { name: /Glossary \(glossary.example.org\)/ })).toHaveAttribute("href", "https://glossary.example.org/status");
  });
});
