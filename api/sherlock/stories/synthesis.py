"""Synthesis cards and questions about the cards (TRD §7.4.1, §8.2 `ask_story`).

"Make sense of this" reads only the selected cards: their text and their fact sheets. The model
writes runs like a story card, with chips naming `<alias>.<fact key>` (`c1.top_value`); code checks
them with the narrator's rules and stores them keyed `<card_id>.<fact key>`, so each chip resolves
through its source card's fact sheet (evidence, the latest value, the `sources_changed` check). A
synthesis card has no fact sheet of its own. When the model can't write a valid synthesis, the card
lists each source card's headline, chips included.
"""

import json
import sqlite3

from pydantic import Field

from sherlock.db.util import new_id, now_iso
from sherlock.errors import ApiError
from sherlock.llm.client import BudgetExceeded, CallScope, LLMClient, LLMUnavailable, StructuredOutputError, data_block
from sherlock.llm.schemas import Run, Story, Strict
from sherlock.stories import narrate as nr
from sherlock.stories import service as stories

MAX_SOURCES = 8
MAX_FACTS = 12

SYNTHESIS = """Several story cards are selected on a canvas. Write one synthesis card that says what they show together: a one-sentence headline and a body of two to four sentences.

Rules:
- Connect or compare the cards; don't repeat each one in turn.
- Every number is a chip: {{"chip": "<card>.<fact key>"}}, using only the keys listed. Text runs never contain digits or numbers in words ("six", "twice").
- Column names and category values are labels: {{"label": "column:<name>"}} or {{"label": "value:<column>:<value>"}}, chosen from the allowed labels.
- Text runs carry the words, including the spaces around chips and labels. A chip or a label is always its own run.
- These are associations in the data: never say causes, because, leads to, results in, drives or due to.

Cards (what each says, then its facts as key · what it is · value):
{cards}
Allowed labels:
{labels}"""

QUESTION = """Answer the question from these story cards only, in one to three sentences. If the cards can't answer it, say so in words and name what they do show.

Rules:
- Every number is a chip: {{"chip": "<card>.<fact key>"}}, using only the keys listed. Text runs never contain digits or numbers in words.
- Column names and category values are labels: {{"label": "column:<name>"}} or {{"label": "value:<column>:<value>"}}, chosen from the allowed labels.
- A chip or a label is always its own run. Associations only: never say causes, because, leads to, results in, drives or due to.

Cards (what each says, then its facts as key · what it is · value):
{cards}
Allowed labels:
{labels}

Question:
{question}"""


class StoryAnswer(Strict):
    prose: list[Run] = Field(min_length=1, max_length=40)


# --- reading cards -----------------------------------------------------------------------------

def plain(body: dict) -> str:
    return " ".join("".join((r.get("value") or "") if r["type"] == "chip" else (r.get("text") or r.get("ref") or "")
                            for r in b["runs"]) for b in body.get("blocks", [])).strip()


def title(db: sqlite3.Connection, card: sqlite3.Row) -> str:
    if card["kind"] == "overview":
        return "Overview"
    if card["widget_id"]:
        w = db.execute("SELECT title FROM widgets WHERE id = ?", (card["widget_id"],)).fetchone()
        if w:
            return w["title"]
    return plain(json.loads(card["headline_json"]))[:80] or card["kind"].capitalize()


def chip_keys(card: sqlite3.Row | dict) -> list[str]:
    parts = ([card["headline"], card["body"]] if isinstance(card, dict)
             else [json.loads(card["headline_json"]), json.loads(card["body_json"])])
    return [r["key"] for p in parts for b in p.get("blocks", []) for r in b["runs"] if r["type"] == "chip" and r.get("key")]


def sources(db: sqlite3.Connection, dataset_id: str, card_ids: list[str]) -> list[tuple[sqlite3.Row, dict]]:
    """The cards whose facts can be cited, with their facts. A card with a fact sheet is cited
    directly; a synthesis or answer card without one stands for the cards its chips name."""
    out: dict[str, tuple[sqlite3.Row, dict]] = {}
    queue = list(card_ids)
    while queue and len(out) < MAX_SOURCES:
        cid = queue.pop(0)
        r = db.execute("SELECT * FROM cards WHERE id = ? AND dataset_id = ? AND deleted_at IS NULL", (cid, dataset_id)).fetchone()
        if r is None or r["id"] in out:
            continue
        sheet = stories.get_sheet(db, r["fact_sheet_id"])
        if sheet and sheet["facts"]:
            out[r["id"]] = (r, sheet["facts"])
        else:
            queue += [k.partition(".")[0] for k in chip_keys(r)]
    return list(out.values())


def _listing(db, cards: list[tuple[sqlite3.Row, dict]]) -> tuple[str, dict, dict, list[str]]:
    """The prompt's card list, the facts by alias key, alias → card id, and the allowed labels."""
    lines, facts, alias, labels = [], {}, {}, []
    for i, (r, card_facts) in enumerate(cards, 1):
        a = f"c{i}"
        alias[a] = r["id"]
        said = (plain(json.loads(r["headline_json"])) + " " + plain(json.loads(r["body_json"]))).strip()
        keys = [k for k in card_facts if k != "n"][:MAX_FACTS - 1] + (["n"] if "n" in card_facts else [])
        lines.append(f"{a} · {title(db, r)}\n  says: {said[:400]}\n" + nr.fact_lines({k: card_facts[k] for k in keys}, f"  {a}."))
        facts.update({f"{a}.{k}": card_facts[k] for k in keys})
        for part in (json.loads(r["headline_json"]), json.loads(r["body_json"])):
            for b in part.get("blocks", []):
                labels += [run["ref"] for run in b["runs"] if run["type"] == "label" and run["ref"].startswith(("column:", "value:"))]
        sheet = db.execute("SELECT depends_columns_json FROM fact_sheets WHERE id = ?", (r["fact_sheet_id"],)).fetchone()
        labels += [f"column:{c}" for c in (json.loads(sheet["depends_columns_json"]) if sheet else [])]
    return "\n\n".join(lines), facts, alias, list(dict.fromkeys(labels))


def _rekey(runs: list[dict], alias: dict, part: str) -> list[dict]:
    """Alias keys back to card IDs; chip IDs prefixed by the part (`h`, `b`) so they're unique on the card."""
    for run in runs:
        if run["type"] == "chip" and run.get("key"):
            a, _, rest = run["key"].partition(".")
            run["key"] = f"{alias[a]}.{rest}"
            run["id"] = part + run["id"]
    return runs


def _check(runs_list: list[list], facts: dict, columns: list[str]) -> None:
    for runs in runs_list:
        nr.to_runs(runs, facts, columns)
        if not nr._words(runs):
            raise ValueError("write words around the chips and labels")
        text = nr.plain(runs)
        if nr.NUMBER_WORDS.search(text):
            raise ValueError(f"a number in words ({nr.NUMBER_WORDS.search(text).group(0)!r}); use a fact chip")
        if nr.CAUSAL.search(text):
            raise ValueError(f"causal wording ({nr.CAUSAL.search(text).group(0)!r}); describe an association instead")


def fallback(db, cards: list[tuple[sqlite3.Row, dict]]) -> tuple[dict, dict]:
    """Each source card's headline as a bullet, its chips keyed through the card."""
    headline = nr.body([{"type": "text", "text": "What these cards say together"}])
    blocks = []
    for r, _ in cards:
        runs = [{"type": "label", "ref": f"card:{r['id']}", "text": title(db, r)}, {"type": "text", "text": ": "}]
        for b in json.loads(r["headline_json"]).get("blocks", [])[:1]:
            for run in b["runs"]:
                run = dict(run)
                if run["type"] == "chip" and run.get("key"):
                    run["key"] = f"{r['id']}.{run['key']}"
                    run["id"] = f"f{len(blocks)}{run['id']}"
                runs.append(run)
        blocks.append({"type": "bullets", "runs": runs})
    return headline, {"blocks": blocks}


# --- synthesis ------------------------------------------------------------------------------------

def synthesize(llm: LLMClient, scope: CallScope, db: sqlite3.Connection, cards: list[tuple[sqlite3.Row, dict]],
               columns: list[str]) -> tuple[dict, dict, bool]:
    listing, facts, alias, labels = _listing(db, cards)

    def check(s: Story) -> None:
        _check([s.headline, s.body], facts, columns)

    prompt = SYNTHESIS.format(cards=data_block(listing), labels=data_block("\n".join(labels) or "none"))
    try:
        s = llm.structured("medium", [{"role": "system", "content": nr.SYSTEM}, {"role": "user", "content": prompt}],
                           Story, purpose="synthesis", scope=scope, validate=check).value
    except (StructuredOutputError, LLMUnavailable, BudgetExceeded):
        h, b = fallback(db, cards)
        return h, b, False
    headline = nr.body(_rekey(nr.to_runs(s.headline, facts, columns), alias, "h"))
    body = nr.body(_rekey(nr.to_runs(s.body, facts, columns), alias, "b"))
    return headline, body, True


def create(db: sqlite3.Connection, bus, llm: LLMClient, scope: CallScope, dataset: sqlite3.Row, card_ids: list[str],
           columns: list[str], kind: str = "synthesis") -> dict:
    """Write, store and emit a synthesis card for the selected cards. `422` with fewer than two."""
    cards = sources(db, dataset["id"], card_ids)
    if len(cards) < 2:
        raise ApiError(422, "invalid", "Select at least two cards to make sense of them.")
    headline, body, by_model = synthesize(llm, scope, db, cards, columns)
    return store(db, bus, dataset, kind, card_ids, headline, body, llm.settings.model_medium if by_model else None)


def store(db: sqlite3.Connection, bus, dataset: sqlite3.Row, kind: str, source_ids: list[str], headline: dict, body: dict,
          narrated_by: str | None) -> dict:
    now = now_iso()
    cid = new_id("crd")
    db.execute(
        "INSERT INTO cards (id, dataset_id, kind, source_card_ids_json, headline_json, body_json, status, version, "
        "narrated_by, verified_at, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'ready', ?, ?, ?, ?, ?)",
        (cid, dataset["id"], kind, json.dumps(list(dict.fromkeys(source_ids))), json.dumps(headline), json.dumps(body),
         dataset["current_version"], narrated_by, now, now, now))
    db.execute("UPDATE datasets SET state_rev = state_rev + 1 WHERE id = ?", (dataset["id"],))
    return stories.emit_card(db, bus, dataset, cid)


def answer(llm: LLMClient, scope: CallScope, db: sqlite3.Connection, cards: list[tuple[sqlite3.Row, dict]],
           columns: list[str], question: str) -> list[dict]:
    """`ask_story`: runs answering the question from the cards, chips keyed `<card_id>.<fact key>`."""
    listing, facts, alias, labels = _listing(db, cards)

    def check(a: StoryAnswer) -> None:
        _check([a.prose], facts, columns)

    prompt = QUESTION.format(cards=data_block(listing), labels=data_block("\n".join(labels) or "none"),
                             question=data_block(question))
    a = llm.structured("medium", [{"role": "system", "content": nr.SYSTEM}, {"role": "user", "content": prompt}],
                       StoryAnswer, purpose="ask_story", scope=scope, validate=check).value
    return _rekey(nr.to_runs(a.prose, facts, columns), alias, "a")


# --- keeping synthesis cards honest (TRD §7.4.1) ---------------------------------------------------

def check_sources(db: sqlite3.Connection, bus, dataset: sqlite3.Row, job_id: str | None = None) -> int:
    """A synthesis or answer card whose cited numbers no longer match its sources' fact sheets becomes
    `sources_changed` and offers Refresh. (With cut 6 there is no material hash: the cited values are
    compared.) Returns how many cards changed status."""
    changed = 0
    rows = db.execute("SELECT * FROM cards WHERE dataset_id = ? AND kind IN ('synthesis', 'answer') AND fact_sheet_id IS NULL "
                      "AND deleted_at IS NULL AND status = 'ready'", (dataset["id"],)).fetchall()
    for r in rows:
        runs = [run for p in (json.loads(r["headline_json"]), json.loads(r["body_json"])) for b in p.get("blocks", [])
                for run in b["runs"] if run["type"] == "chip" and run.get("key")]
        stale = False
        for run in runs:
            f = stories.fact_for(db, dataset["id"], run["key"])
            if f is None or f["formatted"] != run.get("value"):
                stale = True
                break
        if stale:
            db.execute("UPDATE cards SET status = 'sources_changed', updated_at = ? WHERE id = ?", (now_iso(), r["id"]))
            stories.emit_card(db, bus, dataset, r["id"], job_id)
            changed += 1
    return changed


def refresh(db: sqlite3.Connection, bus, llm: LLMClient, scope: CallScope, dataset: sqlite3.Row, card_id: str,
            columns: list[str]) -> dict:
    """Write a synthesis card again from its sources' current facts (its Refresh)."""
    r = stories.card_row(db, card_id)
    cards = sources(db, dataset["id"], json.loads(r["source_card_ids_json"] or "[]"))
    if len(cards) < 2:
        raise ApiError(409, "conflict", "Fewer than two of this card's sources are left.")
    headline, body, by_model = synthesize(llm, scope, db, cards, columns)
    if r["edited_by_user"]:
        db.execute("UPDATE cards SET suggestion_json = ?, status = 'ready', changed_badge = 1, updated_at = ? WHERE id = ?",
                   (json.dumps({"headline": headline, "body": body}), now_iso(), card_id))
    else:
        db.execute("UPDATE cards SET headline_json = ?, body_json = ?, status = 'ready', changed_badge = 1, version = ?, "
                   "narrated_by = ?, verified_at = ?, updated_at = ? WHERE id = ?",
                   (json.dumps(headline), json.dumps(body), dataset["current_version"],
                    llm.settings.model_medium if by_model else None, now_iso(), now_iso(), card_id))
    db.execute("UPDATE datasets SET state_rev = state_rev + 1 WHERE id = ?", (dataset["id"],))
    return stories.emit_card(db, bus, dataset, card_id)
