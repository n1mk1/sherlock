"""The grounding eval (PRD §3 "Unsourced numbers in generated text", STORY-3; TRD §14; Implementation
Plan D8.4): `uv run sherlock eval grounding`.

Each file is imported in a throwaway data directory, built with "Use as is", and its stories written
(the real model unless `LLM_MOCK` is set). Then every story card is checked the way a judge would
check it by hand:

- **Bound.** Every chip that isn't marked unverified names a fact on the card's fact sheet, and shows
  that fact's value.
- **Grounded.** Every cited fact still holds: its query is run again on the version (or a derived fact
  is recomputed), with the 0.5% tolerance of `verify` (TRD §7.4 step 4).
- **No stray numbers.** No text run holds a digit, a Unicode number or a number in words (Roman
  numerals included), and none uses causal wording.
- **Labels.** Every label resolves to a name, and every `value:` label names a value that is in its
  column.

A card the user edited holds their words: its text isn't the model's, and its chips show the latest
sheet's values (TRD §4.6), so only its facts and labels are checked.

A synthesis ("make sense of this") of the first three widget cards is written too and checked the
same way, its chips resolving through the cards it cites. The report counts each check, and says
how many cards the model wrote (the rest fell back to the fact sheet's bullets). The PRD target is
100% grounded.
"""

import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from sherlock.eval.ask import SAMPLES, ready
from sherlock.llm.text import has_digits
from sherlock.stories import narrate as nr

API = "/api/v1"
DEFAULT_SETS = ["titanic3.csv", "sales_dated.csv"]


@dataclass
class Tally:
    file: str
    cards: int = 0
    by_model: int = 0
    chips: int = 0
    chips_ok: int = 0
    facts_checked: int = 0
    facts_stale: int = 0
    text_with_numbers: int = 0
    causal: int = 0
    labels_bad: int = 0
    synthesis: str = "not written"
    problems: list[str] = field(default_factory=list)


def _wait_stories(client, ds_id: str, timeout_s: float = 900) -> None:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        jobs = client.get(f"{API}/jobs?dataset_id={ds_id}").json()
        if isinstance(jobs, list) and any(j["kind"] == "stories" for j in jobs) \
                and all(j["status"] in ("done", "failed", "cancelled") for j in jobs):
            return
        time.sleep(1)
    raise TimeoutError("the stories didn't finish")


def _runs(card: dict):
    for part in ("headline", "body"):
        for b in card[part]["blocks"]:
            yield from b["runs"]


def check_card(db, cache, settings, dataset, card: dict, tally: Tally, what: str) -> None:
    from sherlock.rows.query import ident
    from sherlock.stories import service as stories
    from sherlock.stories.facts import verify
    from sherlock.widgets import service as ws

    edited = bool(card.get("edited_by_user"))
    by_sheet: dict[str, list[str]] = {}
    value_labels: list[str] = []
    for run in _runs(card):
        if run["type"] == "chip":
            if run.get("unverified"):
                continue
            tally.chips += 1
            key = run.get("key") or ""
            f = card["facts"].get(key)
            if f is None:
                tally.problems.append(f"{what}: chip {key!r} names no fact")
            elif not edited and f["formatted"] != run["value"]:
                tally.problems.append(f"{what}: chip {key!r} shows {run['value']} but its fact is {f['formatted']}")
            else:
                tally.chips_ok += 1
            # The fact's own sheet: the card's, or (synthesis) the cited card's.
            if card.get("fact_sheet_id") and key in (stories.get_sheet(db, card["fact_sheet_id"]) or {}).get("facts", {}):
                by_sheet.setdefault(card["fact_sheet_id"], []).append(key)
            elif "." in key:
                cid, _, fkey = key.partition(".")
                r = db.execute("SELECT fact_sheet_id FROM cards WHERE id = ?", (cid,)).fetchone()
                if r and r["fact_sheet_id"]:
                    by_sheet.setdefault(r["fact_sheet_id"], []).append(fkey)
        elif run["type"] == "text":
            if edited:
                continue
            text = run["text"]
            if has_digits(text) or nr.number_in_words(text):
                tally.text_with_numbers += 1
                tally.problems.append(f"{what}: a number in a text run: {text[:60]!r}")
            if nr.CAUSAL.search(text):
                tally.causal += 1
                tally.problems.append(f"{what}: causal wording: {text[:60]!r}")
        elif run["type"] == "label":
            if not (run.get("text") or "").strip():
                tally.labels_bad += 1
                tally.problems.append(f"{what}: label {run.get('ref')!r} has no text")
            elif (run.get("ref") or "").startswith("value:"):
                value_labels.append(run["ref"])
    env = ws.Env(settings, db, cache, None)
    for sheet_id, keys in by_sheet.items():
        sheet = stories.get_sheet(db, sheet_id)
        cited = sorted({k for k in keys if k in sheet["facts"]})
        with ws.connection(env, dataset, sheet["version"]) as conn:
            stale = verify(conn, sheet["facts"], cited)  # the whole sheet: a derived fact reads the facts it's from
        tally.facts_checked += len(cited)
        tally.facts_stale += len(stale)
        tally.problems += [f"{what}: fact {k!r} no longer holds on v{sheet['version']}" for k in stale]
    if value_labels and dataset is not None:
        with ws.connection(env, dataset, dataset["current_version"]) as conn:
            columns = {r[0] for r in conn.execute("DESCRIBE t").fetchall()}
            for ref in value_labels:
                col, _, val = ref[len("value:"):].partition(":")
                found = col in columns and conn.execute(
                    f"SELECT 1 FROM t WHERE CAST({ident(col)} AS VARCHAR) = ? LIMIT 1", [val]).fetchone()
                if not found:
                    tally.labels_bad += 1
                    tally.problems.append(f"{what}: the label {ref!r} names no value of the file")


def check_dataset(client, db, settings, filename: str, ds_id: str) -> Tally:
    """Every story card of a built dataset (not the synthesis, which `evaluate` writes)."""
    tally = Tally(filename)
    dataset = db.execute("SELECT * FROM datasets WHERE id = ?", (ds_id,)).fetchone()
    for c in client.get(f"{API}/datasets/{ds_id}/cards").json():
        tally.cards += 1
        tally.by_model += bool(c["narrated_by"])
        check_card(db, client.app.state.duckdb, settings, dataset, c, tally, c["kind"] + ":" + c["id"][-6:])
    return tally


def evaluate(client, files: list[str]) -> list[Tally]:
    from sherlock.db.connection import connect
    from sherlock.llm.client import CallScope, LLMClient
    from sherlock.stories import synthesis

    app = client.app
    out = []
    for filename in files:
        ds_id = ready(client, filename)
        _wait_stories(client, ds_id)
        db = connect(app.state.settings)
        try:
            tally = check_dataset(client, db, app.state.settings, filename, ds_id)
            dataset = db.execute("SELECT * FROM datasets WHERE id = ?", (ds_id,)).fetchone()
            cards = client.get(f"{API}/datasets/{ds_id}/cards").json()
            widget_cards = [c["id"] for c in cards if c["kind"] == "widget"][:3]
            if len(widget_cards) >= 2:
                columns = [col["name"] for col in client.get(f"{API}/datasets/{ds_id}/datacard").json()["columns"]]
                scope = CallScope(user_id=dataset["user_id"], dataset_id=ds_id)
                card = synthesis.create(db, None, LLMClient(app.state.settings), scope, dataset, widget_cards, columns)
                tally.synthesis = "by the model" if card["narrated_by"] else "fallback bullets"
                tally.cards += 1
                tally.by_model += bool(card["narrated_by"])
                check_card(db, app.state.duckdb, app.state.settings, dataset, card, tally, "synthesis")
        finally:
            db.close()
        out.append(tally)
    return out


def report(tallies: list[Tally]) -> str:
    lines = ["| File | Cards (by the model) | Chips matching their fact | Facts re-run and holding | Text runs with numbers | "
             "Causal wording | Bad labels | Synthesis |", "|---|---|---|---|---|---|---|---|"]
    for t in tallies:
        lines.append(f"| {t.file} | {t.cards} ({t.by_model}) | {t.chips_ok} of {t.chips} | "
                     f"{t.facts_checked - t.facts_stale} of {t.facts_checked} | {t.text_with_numbers} | {t.causal} | "
                     f"{t.labels_bad} | {t.synthesis} |")
    chips, ok = sum(t.chips for t in tallies), sum(t.chips_ok for t in tallies)
    problems = [p for t in tallies for p in t.problems]
    lines += ["", f"Grounded {ok} of {chips} chips.",
              "No problems found." if not problems else "Problems:\n" + "\n".join(f"- {p}" for p in problems)]
    return "\n".join(lines)


def run(files: list[str] | None = None) -> str:
    from fastapi.testclient import TestClient

    from sherlock.config import get_settings
    from sherlock.main import create_app

    files = files or DEFAULT_SETS
    missing = [f for f in files if not (SAMPLES / f).exists()]
    if missing:
        raise SystemExit(f"no such sample file: {', '.join(missing)}")
    with tempfile.TemporaryDirectory(prefix="sherlock-grounding-") as tmp:
        os.environ["DATA_DIR"] = tmp
        os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmp, 'sherlock.db').as_posix()}"
        os.environ.setdefault("JOB_WORKERS", "2")
        get_settings.cache_clear()
        with TestClient(create_app()) as client:
            tallies = evaluate(client, files)
        get_settings.cache_clear()
    return report(tallies)
