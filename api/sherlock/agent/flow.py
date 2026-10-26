"""Chat on the Flow canvas (TRD §7.4.1, §8.2): "make sense of this", `ask_story`, and Add to Flow.

- **Make sense of this** writes a synthesis card from the selected cards (`stories/synthesis.py`) and
  places it right of them on the canvas with "summarized in" edges from each source
  (`add_canvas_node`, `add_canvas_edge`).
- **`ask_story`** answers a question from the selected cards (or the canvas's cards, or all cards)
  with chips keyed `<card_id>.<fact key>`; the answer offers Add to Flow.
- **Add to Flow** (`POST /messages/{mid}/pin` with `target: "flow"`) turns an answer's text into an
  `answer` card bound to its own fact sheet: each chip's fact is copied from the result cell it names
  (with that query as its evidence) or from the card fact it cites.
"""

import json
import re
import sqlite3

from sherlock.agent.answerers import CantAnswer
from sherlock.agent.compose import text_block
from sherlock.canvas import service as canvas
from sherlock.db.util import new_id, now_iso
from sherlock.errors import ApiError
from sherlock.llm.client import CallScope, LLMClient
from sherlock.stories import service as stories
from sherlock.stories import synthesis

MAKE_SENSE = re.compile(r"\b(make sense|sum (?:this|these|them|it) up|summari[sz]e|synthes[iy][sz]e|synthesis"
                        r"|what do (?:these|they|the cards) (?:say|show|mean) together|tie (?:these|them) together)\b", re.I)
MAX_CARDS = 8


def _cards_in_view(db: sqlite3.Connection, dataset_id: str, selected: list[str]) -> list[str]:
    """The cards a Flow question is about: the selection, else those on the canvas, else all of them."""
    if selected:
        return selected[:MAX_CARDS]
    doc, _ = canvas.read(db, dataset_id)
    placed = [n["sherlock"]["card_id"] for n in doc["nodes"] if (n.get("sherlock") or {}).get("card_id")]
    if placed:
        return placed[:MAX_CARDS]
    rows = db.execute("SELECT c.id FROM cards c LEFT JOIN widgets w ON w.id = c.widget_id WHERE c.dataset_id = ? "
                      "AND c.deleted_at IS NULL ORDER BY c.kind != 'overview', w.order_no LIMIT ?", (dataset_id, MAX_CARDS))
    return [r["id"] for r in rows]


def card_sources(db: sqlite3.Connection, cards: list[tuple[sqlite3.Row, dict]]) -> list[dict]:
    return [{"kind": "card", "card_id": r["id"], "label": synthesis.title(db, r)} for r, _ in cards]


def make_sense(db, bus, llm: LLMClient, scope: CallScope, dataset: sqlite3.Row, selected: list[str],
               columns: list[str]) -> tuple[list[dict], list[dict], dict]:
    """(blocks, sources, card): the synthesis card, written, stored and placed."""
    if len(selected) < 2:
        raise CantAnswer("Select at least two cards to make sense of them.")
    try:
        card = synthesis.create(db, bus, llm, scope, dataset, selected, columns)
    except ApiError as exc:
        raise CantAnswer(exc.message) from exc

    def place(doc: dict) -> None:
        nodes = [n for n in (canvas.card_node(doc, c) for c in selected) if n]
        x, y = canvas.beside(nodes, doc)
        node = canvas.add_card_node(doc, card["id"], x, y)
        for n in nodes:
            canvas.add_edge(doc, n["id"], node["id"], "summarized in", "summarized_in")

    canvas.mutate(db, bus, dataset, place)
    left: list[str] = []
    cited = synthesis.sources(db, dataset["id"], selected, left)
    blocks = [text_block([{"type": "text", "text": f"I added a synthesis of {len(cited)} cards to the canvas: "},
                          *card["headline"]["blocks"][0]["runs"]]),
              {"type": "text", "body": card["body"]}]
    if left:  # cards whose numbers may not hold aren't cited (plan 1.3)
        blocks.append(text_block([{"type": "text", "text": synthesis.left_out_note(left)}]))
    return blocks, card_sources(db, cited), card


def ask_story(db, llm: LLMClient, scope: CallScope, dataset: sqlite3.Row, question: str, selected: list[str],
              columns: list[str]) -> tuple[list[dict], list[dict]]:
    ids = _cards_in_view(db, dataset["id"], selected)
    left: list[str] = []
    cards = synthesis.sources(db, dataset["id"], ids, left)
    if not cards:
        raise CantAnswer(synthesis.left_out_note(left) if left else "There are no story cards to answer from yet.")
    runs = synthesis.answer(llm, scope, db, cards, columns, question)
    blocks = [text_block(runs)]
    if left:  # only usable cards are read (plan 1.3); the answer says which weren't
        blocks.append(text_block([{"type": "text", "text": synthesis.left_out_note(left)}]))
    return blocks, card_sources(db, cards)


# --- Add to Flow ----------------------------------------------------------------------------------

def _chips(block: dict) -> list[dict]:
    return [r for b in block.get("body", {}).get("blocks", []) for r in b["runs"] if r["type"] == "chip"]


def add_to_flow(db: sqlite3.Connection, bus, dataset: sqlite3.Row, message: sqlite3.Row, block_index: int) -> dict:
    """The answer's text block as an `answer` card on the canvas. `422` for a block with no grounded text."""
    blocks = json.loads(message["blocks_json"])
    if not 0 <= block_index < len(blocks):
        raise ApiError(422, "invalid", "block_index: no such block in this message")
    if blocks[block_index]["type"] == "text" and blocks[block_index].get("web") == "context":
        # A web answer has no numbers from the data, so a newer version doesn't make it older (unlike 2b.4's rule below).
        return _add_web(db, bus, dataset, message, blocks[block_index], blocks)
    if message["version"] is not None and message["version"] != dataset["current_version"]:
        # Plan 2b.4: a card's numbers are on the current version, and this answer's are from an older one.
        raise ApiError(409, "conflict", f"This answer was worked out on version {message['version']}; the data is now "
                                        f"version {dataset['current_version']}. Ask again to add the current numbers to Flow.")
    block = blocks[block_index]
    if block["type"] != "text" or not _chips(block) or block.get("labeled") == "general":
        raise ApiError(422, "invalid", "Only an answer's text with its numbers can be added to Flow.")
    sources = json.loads(message["sources_json"])
    sql_of = {s.get("result"): s.get("sql") for s in sources if s.get("result")}
    facts, depends, cited = {}, [], []
    for chip in _chips(block):
        key = chip.get("key")
        if not key or chip.get("unverified"):
            continue
        if "." in key and key.startswith("crd_"):  # a story card's fact (ask_story)
            f = stories.fact_for(db, dataset["id"], key)
            if f is None:
                raise ApiError(409, "conflict", "A card this answer cites has changed; ask again to add it.")
            facts[key] = f
            cited.append(key.partition(".")[0])
            continue
        rid, _, cell = key.partition(":")
        r, _, c = cell.partition(":")
        facts[key] = {"value": chip.get("raw"), "formatted": chip["value"], "label": "result of the answer's query",
                      "sql": sql_of.get(rid), "cell": [int(r), int(c)] if r.isdigit() and c.isdigit() else None}
    focus = json.loads(message["focus_json"] or "{}")
    # The columns its numbers read: the result's, and every column its queries name (so a change to one
    # reaches it, plan 2b.2).
    depends = sorted(stories.answer_depends({"depends_columns": focus.get("columns") or [], "facts": facts}))
    question = db.execute("SELECT text FROM messages WHERE dataset_id = ? AND role = 'user' AND created_at <= ? "
                          "ORDER BY created_at DESC, id DESC LIMIT 1", (dataset["id"], message["created_at"])).fetchone()
    sheet_id = new_id("fs")
    db.execute("INSERT INTO fact_sheets (id, dataset_id, widget_id, version, facts_json, depends_columns_json, material_hash, "
               "created_at) VALUES (?, ?, NULL, ?, ?, ?, '', ?)",
               (sheet_id, dataset["id"], dataset["current_version"], json.dumps(facts, default=str), json.dumps(depends), now_iso()))
    headline = {"blocks": [{"type": "paragraph", "runs": [
        {"type": "label", "ref": "question", "text": (question["text"] if question else "An answer")[:160]}]}]}
    body = {"blocks": [{"type": b.get("type", "paragraph"), "runs": b["runs"]} for b in block["body"]["blocks"]]}
    now = now_iso()
    cid = new_id("crd")
    db.execute(
        "INSERT INTO cards (id, dataset_id, kind, source_card_ids_json, headline_json, body_json, fact_sheet_id, status, "
        "version, verified_at, created_at, updated_at) VALUES (?, ?, 'answer', ?, ?, ?, ?, 'ready', ?, ?, ?, ?)",
        (cid, dataset["id"], json.dumps(list(dict.fromkeys(cited))) if cited else None, json.dumps(headline), json.dumps(body),
         sheet_id, dataset["current_version"], now, now, now))

    def place(doc: dict) -> None:
        x, y = canvas.beside([], doc)
        canvas.add_card_node(doc, cid, x, y)

    canvas.mutate(db, bus, dataset, place)
    return stories.emit_card(db, bus, dataset, cid)


def _add_web(db: sqlite3.Connection, bus, dataset: sqlite3.Row, message: sqlite3.Row, block: dict, blocks: list) -> dict:
    """A web answer (TRD §8.2 `web_context`) as an `answer` card: its text with each citation as "[n]", then its
    sources, each with its address and the day it was retrieved, so the card and the notebook keep the
    citations. Its fact sheet is empty: nothing on it is a number from the data, and no chip is made."""
    listing = next((b for b in blocks if b.get("type") == "web_sources"), {"results": []})
    runs = [{"type": "label", "ref": f"web:{r['n']}", "text": f"[{r['n']}]"} if r["type"] == "cite" else r
            for p in block["body"]["blocks"] for r in p["runs"]]
    cites = []
    for r in listing["results"]:
        cites += [{"type": "label", "ref": f"web:{r['n']}", "text": f"[{r['n']}] {r['title']}, {r['url']}, retrieved {r['retrieved_at']}"},
                  {"type": "text", "text": "\n"}]
    body = {"blocks": [{"type": "paragraph", "runs": runs}] + ([{"type": "bullets", "runs": cites[:-1]}] if cites else [])}
    question = db.execute("SELECT text FROM messages WHERE dataset_id = ? AND role = 'user' AND created_at <= ? "
                          "ORDER BY created_at DESC, id DESC LIMIT 1", (dataset["id"], message["created_at"])).fetchone()
    headline = {"blocks": [{"type": "paragraph", "runs": [
        {"type": "label", "ref": "question", "text": (question["text"] if question else "From the web")[:160]}]}]}
    sheet_id, cid, now = new_id("fs"), new_id("crd"), now_iso()
    db.execute("INSERT INTO fact_sheets (id, dataset_id, widget_id, version, facts_json, depends_columns_json, material_hash, "
               "created_at) VALUES (?, ?, NULL, ?, '{}', '[]', '', ?)", (sheet_id, dataset["id"], dataset["current_version"], now))
    db.execute(
        "INSERT INTO cards (id, dataset_id, kind, source_card_ids_json, headline_json, body_json, fact_sheet_id, status, "
        "version, verified_at, created_at, updated_at) VALUES (?, ?, 'answer', NULL, ?, ?, ?, 'ready', ?, ?, ?, ?)",
        (cid, dataset["id"], json.dumps(headline), json.dumps(body), sheet_id, dataset["current_version"], now, now, now))

    def place(doc: dict) -> None:
        x, y = canvas.beside([], doc)
        canvas.add_card_node(doc, cid, x, y)

    canvas.mutate(db, bus, dataset, place)
    return stories.emit_card(db, bus, dataset, cid)
