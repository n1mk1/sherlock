// The inline card editor (App Flow §11, PRD STORY-7): TipTap with chips and labels as atom nodes.
// Typing `/` opens the picker of this card's facts; choosing one inserts its chip, so the number
// stays bound to the fact sheet. Numbers typed by hand are saved as text and the server marks them
// unverified. Loaded only when a card is edited.
import { mergeAttributes, Node, type JSONContent } from "@tiptap/core";
import { EditorContent, useEditor, type Editor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { useMemo, useRef, useState } from "react";
import type { Card, CardBody, Run } from "@/api/types";
import { Button } from "@/components/ui/button";

const ChipNode = Node.create({
  name: "chip",
  group: "inline",
  inline: true,
  atom: true,
  addAttributes: () => ({ id: { default: null }, key: { default: null }, value: { default: "" }, unverified: { default: false } }),
  parseHTML: () => [{ tag: "span[data-chip]" }],
  renderHTML: ({ node, HTMLAttributes }) => [
    "span",
    mergeAttributes(HTMLAttributes, {
      "data-chip": "",
      class: "mx-px rounded-[6px] border border-[color-mix(in_srgb,var(--info)_35%,transparent)] bg-info-soft px-[5px] font-mono text-[12.5px]",
    }),
    String(node.attrs.value),
  ],
  renderText: ({ node }) => String(node.attrs.value),
});

const LabelNode = Node.create({
  name: "label",
  group: "inline",
  inline: true,
  atom: true,
  addAttributes: () => ({ ref: { default: null }, text: { default: "" } }),
  parseHTML: () => [{ tag: "span[data-label]" }],
  renderHTML: ({ node, HTMLAttributes }) => ["span", mergeAttributes(HTMLAttributes, { "data-label": "", class: "font-medium" }), String(node.attrs.text)],
  renderText: ({ node }) => String(node.attrs.text),
});

function runsToContent(runs: Run[]): JSONContent[] {
  return runs.flatMap((r): JSONContent[] => {
    if (r.type === "chip") return [{ type: "chip", attrs: { id: r.id, key: r.key, value: r.value, unverified: r.unverified } }];
    if (r.type === "label") return [{ type: "label", attrs: { ref: r.ref, text: r.text ?? "" } }];
    return r.text ? [{ type: "text", text: r.text }] : [];
  });
}

export function toDoc(body: CardBody): JSONContent {
  const content: JSONContent[] = [];
  let list: JSONContent | null = null;
  for (const b of body.blocks) {
    const para = { type: "paragraph", content: runsToContent(b.runs) };
    if (b.type === "bullets") {
      if (!list) content.push((list = { type: "bulletList", content: [] }));
      list.content!.push({ type: "listItem", content: [para] });
    } else {
      list = null;
      content.push(para);
    }
  }
  return { type: "doc", content: content.length ? content : [{ type: "paragraph" }] };
}

function contentToRuns(nodes: JSONContent[] = []): Run[] {
  return nodes.map((n): Run => {
    if (n.type === "chip") return { type: "chip", id: n.attrs?.id ?? `e${Math.random().toString(36).slice(2, 7)}`, key: n.attrs?.key, value: n.attrs?.value, unverified: !!n.attrs?.unverified };
    if (n.type === "label") return { type: "label", ref: n.attrs?.ref, text: n.attrs?.text };
    return { type: "text", text: n.text ?? "" };
  });
}

export function fromDoc(doc: JSONContent): CardBody {
  const blocks: CardBody["blocks"] = [];
  for (const n of doc.content ?? []) {
    if (n.type === "bulletList") {
      for (const li of n.content ?? []) for (const p of li.content ?? []) blocks.push({ type: "bullets", runs: contentToRuns(p.content) });
    } else {
      const runs = contentToRuns(n.content);
      if (runs.length) blocks.push({ type: "paragraph", runs });
    }
  }
  return { blocks };
}

function useCardEditor(body: CardBody, onSlash: (e: Editor) => void, single: boolean) {
  const self = useRef<Editor | null>(null);
  const editor = useEditor({
    extensions: [StarterKit.configure({ heading: false, codeBlock: false, blockquote: false, horizontalRule: false }), ChipNode, LabelNode],
    content: toDoc(single ? { blocks: body.blocks.slice(0, 1) } : body),
    editorProps: {
      attributes: { class: "rounded-md border border-input bg-background px-2.5 py-1.5 outline-none focus:border-accent" },
      handleKeyDown: (_view, event) => {
        if (event.key === "/") {
          if (self.current) onSlash(self.current);
          return true;
        }
        return single && event.key === "Enter";
      },
    },
  });
  self.current = editor;
  return editor;
}

export function CardEditor({ card, source, onSave, onCancel }: {
  card: Card; source: { headline: CardBody; body: CardBody }; onSave: (headline: CardBody, body: CardBody) => void; onCancel: () => void;
}) {
  const [picker, setPicker] = useState<Editor | null>(null);
  const [query, setQuery] = useState("");
  const headline = useCardEditor(source.headline, setPicker, true);
  const body = useCardEditor(source.body, setPicker, false);
  const facts = useMemo(() => Object.entries(card.facts)
    .filter(([k, f]) => !query || `${k} ${f.label}`.toLowerCase().includes(query.toLowerCase())), [card.facts, query]);

  const insert = (key: string) => {
    if (!picker) return;
    picker.chain().focus().insertContent({ type: "chip", attrs: { id: `p${Date.now().toString(36)}`, key, value: card.facts[key].formatted, unverified: false } }).run();
    setPicker(null);
    setQuery("");
  };

  return (
    <div className="flex flex-col gap-2 text-[14px]" onKeyDown={(e) => e.key === "Escape" && !picker && onCancel()}>
      <label className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Headline</label>
      <EditorContent editor={headline} className="font-serif text-[16px] font-semibold" />
      <label className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Body</label>
      <EditorContent editor={body} className="leading-relaxed [&_ul]:list-disc [&_ul]:pl-4" />
      {picker && (
        <div className="rounded-md border border-border bg-popover p-2 shadow-[var(--shadow-overlay)]" role="listbox" aria-label="Insert a number">
          <input autoFocus value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Find a number…"
            onKeyDown={(e) => {
              if (e.key === "Escape") { setPicker(null); picker.commands.focus(); }
              if (e.key === "Enter" && facts[0]) insert(facts[0][0]);
            }}
            className="mb-1.5 h-7 w-full rounded border border-input bg-card px-2 text-[13px] outline-none" />
          <ul className="max-h-[180px] overflow-y-auto">
            {facts.map(([k, f]) => (
              <li key={k}>
                <button type="button" onClick={() => insert(k)} className="flex w-full items-center gap-2 rounded px-1.5 py-1 text-left text-[13px] hover:bg-secondary">
                  <span className="min-w-0 flex-1 truncate">{f.label}</span>
                  <span className="font-mono text-[12px]">{f.formatted}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="text-[12px] text-muted-foreground">Type / to insert a number from the facts. Numbers you type yourself are marked unverified.</p>
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="ghost" onClick={onCancel}>Cancel</Button>
        <Button size="sm" variant="primary" disabled={!headline || !body}
          onClick={() => headline && body && onSave(fromDoc(headline.getJSON()), fromDoc(body.getJSON()))}>Save</Button>
      </div>
    </div>
  );
}
