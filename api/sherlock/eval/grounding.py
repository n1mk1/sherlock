"""The grounding eval (TRD §14, Implementation Plan D8.4): `uv run sherlock eval grounding`.

Each file is imported in a throwaway data directory, built with "Use as is", and its stories written
(the real model unless `LLM_MOCK` is set). Then every story card is checked the way a judge would
check it by hand:

- every chip names a fact on the card's fact sheet, and shows that fact's value;
- every cited fact still holds: its query is run again on the version (0.5% tolerance);
- no text run holds a digit or a number in words, and none uses causal wording;
- every label resolves to a name.

A synthesis ("make sense of this") of the first three widget cards is written too and checked the
same way, its chips resolving through the cards it cites. The report counts each check, and says
how many cards the model wrote (the rest fell back to the fact sheet's bullets).
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
        if any(j["kind"] == "stories" for j in jobs) and all(j["status"] in ("done", "failed", "cancelled") for j in jobs):
            return
        time.sleep(1)
    raise TimeoutError("the stories didn't finish")


def _runs(card: dict):
    for part in ("headline", "body"):
        for b in card[part]["blocks"]:
            yield from b["runs"]


def check_card(db, cache, settings, dataset, card: dict, tally: Tally, what: str) -> None:
    from sherlock.stories import service as stories
    from sherlock.stories.facts import verify
    from sherlock.widgets import service as ws

    by_sheet: dict[str, list[str]] = {}
    for run in _runs(card):
        if run["type"] == "chip":
            if run.get("unverified"):
                continue
            tally.chips += 1
            key = run.get("key") or ""
            f = card["facts"].get(key)
            if f is None:
                tally.problems.append(f"{what}: chip {key!r} names no fact")
            elif f["formatted"] != run["value"]:
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
            text = run["text"]
            if has_digits(text) or nr.NUMBER_WORDS.search(text):
                tally.text_with_numbers += 1
                tally.problems.append(f"{what}: a number in a text run: {text[:60]!r}")
            if nr.CAUSAL.search(text):
                tally.causal += 1
                tally.problems.append(f"{what}: causal wording: {text[:60]!r}")
        elif run["type"] == "label" and not (run.get("text") or "").strip():
            tally.labels_bad += 1
            tally.problems.append(f"{what}: label {run.get('ref')!r} has no text")
    env = ws.Env(settings, db, cache, None)
    for sheet_id, keys in by_sheet.items():
        sheet = stories.get_sheet(db, sheet_id)
        cited = sorted({k for k in keys if k in sheet["facts"]})
        with ws.connection(env, dataset, sheet["version"]) as conn:
            stale = verify(conn, sheet["facts"], cited)  # the whole sheet: a derived fact reads the facts it's from
        facts = cited
        tally.facts_checked += len(facts)
        tally.facts_stale += len(stale)
        tally.problems += [f"{what}: fact {k!r} no longer holds on v{sheet['version']}" for k in stale]


def evaluate(client, files: list[str]) -> list[Tally]:
    from sherlock.db.connection import connect
    from sherlock.llm.client import CallScope, LLMClient
    from sherlock.stories import synthesis

    app = client.app
    out = []
    for filename in files:
        tally = Tally(filename)
        ds_id = ready(client, filename)
        _wait_stories(client, ds_id)
        cards = client.get(f"{API}/datasets/{ds_id}/cards").json()
        db = connect(app.state.settings)
        try:
            dataset = db.execute("SELECT * FROM datasets WHERE id = ?", (ds_id,)).fetchone()
            for c in cards:
                tally.cards += 1
                tally.by_model += bool(c["narrated_by"])
                check_card(db, app.state.duckdb, app.state.settings, dataset, c, tally, c["kind"] + ":" + c["id"][-6:])
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
             "Causal wording | Synthesis |", "|---|---|---|---|---|---|---|"]
    for t in tallies:
        lines.append(f"| {t.file} | {t.cards} ({t.by_model}) | {t.chips_ok} of {t.chips} | "
                     f"{t.facts_checked - t.facts_stale} of {t.facts_checked} | {t.text_with_numbers} | {t.causal} | {t.synthesis} |")
    problems = [p for t in tallies for p in t.problems]
    lines += ["", "No problems found." if not problems else "Problems:\n" + "\n".join(f"- {p}" for p in problems)]
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
