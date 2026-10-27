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
- **Claims.** "Highest" and "most" sit next to a top the facts name, "lowest" and "least"
  next to the bottom group, a rank next to the factor of that rank, and "rising" or "falling" go with a
  trend that does (`narrate.claims`). The report counts the claims checked and the ones that failed.

A card the user edited holds their words: its text isn't the model's, and its chips show the latest
sheet's values (TRD §4.6), so only its facts and labels are checked.

A synthesis ("make sense of this") of the first three widget cards is written too and checked the
same way, its chips resolving through the cards it cites. The report counts each check, and says
how many cards the model wrote (the rest fell back to the fact sheet's bullets). The PRD target is
100% grounded.

Then the **stale-reuse** scenario, which needs no model call: one of the synthesis's cards
is deleted and restored, and the synthesis must no longer be `ready`; then, with "Story updates: Ask
first", one cell of the column most cards read is edited, and after the cascade the overview isn't
`ready`, the cascade's audit and a fresh `audit()` find 0 cards to fix, and the notebook carries an
"Out of date" note for every card that isn't ready.
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
    claims_checked: int = 0
    claims_failed: int = 0
    synthesis: str = "not written"
    problems: list[str] = field(default_factory=list)
    stale: "StaleReuse | None" = None


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


def card_claims(card: dict) -> tuple[int, list[str]]:
    """(claims checked, claims that fail) in a card's headline and body, its chips read through its facts."""
    facts = card.get("facts") or {}
    checked, wrong = 0, []
    for part in ("headline", "body"):
        for b in card[part]["blocks"]:
            chip_facts = {r["id"]: (r.get("key") or "", facts.get(r.get("key") or "")) for r in b["runs"]
                          if r["type"] == "chip" and r.get("id")}
            n, bad = nr.claims(b["runs"], chip_facts, facts)
            checked, wrong = checked + n, wrong + bad
    return checked, wrong


def check_card(db, cache, settings, dataset, card: dict, tally: Tally, what: str) -> None:
    from sherlock.rows.query import ident
    from sherlock.stories import service as stories
    from sherlock.stories.facts import verify
    from sherlock.widgets import service as ws

    edited = bool(card.get("edited_by_user"))
    if not edited:  # a card the user edited holds their words, not the model's claims
        n, wrong = card_claims(card)
        tally.claims_checked += n
        tally.claims_failed += len(wrong)
        tally.problems += [f"{what}: {w}" for w in wrong]
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


@dataclass
class StaleReuse:
    file: str
    column: str = ""
    synthesis_after_delete: str = "not checked"
    overview: str = "none"
    outdated_cards: int = 0
    notebook_notes: int = 0
    notes_expected: int = 0
    audited: int | None = None
    problems: list[str] = field(default_factory=list)


def _settle(client, ds_id: str, timeout_s: float = 300) -> list[dict]:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        jobs = client.get(f"{API}/jobs?dataset_id={ds_id}").json()
        if isinstance(jobs, list) and all(j["status"] in ("done", "failed", "cancelled") for j in jobs):
            return jobs
        time.sleep(1)
    raise TimeoutError("the jobs didn't finish")


def _column_to_edit(client, db, ds_id: str) -> tuple[str, str] | None:
    """The column most widget cards read (a number if one is read, else text), and its type."""
    from collections import Counter

    from sherlock.stories import service as stories

    types = {c["name"]: c["type"] for c in client.get(f"{API}/datasets/{ds_id}/datacard").json()["columns"]}
    counts: Counter = Counter()
    for c in client.get(f"{API}/datasets/{ds_id}/cards").json():
        sheet = stories.get_sheet(db, c["fact_sheet_id"]) if c["kind"] == "widget" else None
        counts.update(col for col in (sheet or {}).get("depends_columns", []) if col in types)
    ranked = [col for col, _ in counts.most_common()]
    for kinds in (("int", "float"), ("category", "text")):
        for col in ranked:
            if types[col] in kinds:
                return col, types[col]
    return None


def _edited(value, kind: str) -> str:
    if kind == "int":
        return str(int(value) + 1)
    if kind == "float":
        return str(round(float(value) + 1, 4))
    return f"{value} (edited)"


def stale_reuse(client, db, settings, filename: str, ds_id: str, synthesis_id: str | None) -> StaleReuse:
    """Plan 1.3's scenario: nothing that isn't usable passes for current (see the module docstring)."""
    from sherlock.notebook import exporter
    from sherlock.rows.query import ident
    from sherlock.stories import trust
    from sherlock.widgets import service as ws

    out = StaleReuse(filename)
    if synthesis_id:
        syn = client.get(f"{API}/cards/{synthesis_id}").json()
        source = next((r["key"].partition(".")[0] for r in _runs(syn) if r["type"] == "chip" and r.get("key")), None)
        if source:
            client.delete(f"{API}/cards/{source}")
            out.synthesis_after_delete = client.get(f"{API}/cards/{synthesis_id}").json()["status"]
            if out.synthesis_after_delete == "ready":
                out.problems.append("a synthesis citing a deleted card stayed ready")
            client.post(f"{API}/cards/{source}/restore")
    picked = _column_to_edit(client, db, ds_id)
    if picked is None:
        out.problems.append("no card reads a column this scenario can edit")
        return out
    out.column, kind = picked
    client.put(f"{API}/me/settings", json={"story_updates": "ask"})
    try:
        dataset = db.execute("SELECT * FROM datasets WHERE id = ?", (ds_id,)).fetchone()
        env = ws.Env(settings, db, client.app.state.duckdb, None)
        col = ident(out.column)
        with ws.connection(env, dataset, dataset["current_version"]) as conn:
            row_id, value = conn.execute(f"SELECT _row_id, {col} FROM t WHERE {col} IS NOT NULL ORDER BY _row_id LIMIT 1").fetchone()
        edits = [{"row_id": row_id, "column": out.column, "value": _edited(value, kind)}]
        r = client.post(f"{API}/datasets/{ds_id}/edits", json={"base_version": dataset["current_version"], "edits": edits})
        if r.status_code != 201:
            out.problems.append(f"the edit was refused: {r.text[:120]}")
            return out
        jobs = _settle(client, ds_id)
        cascade = next((j for j in jobs if j["kind"] == "cascade"), None)  # the newest first
        out.audited = ((cascade or {}).get("result") or {}).get("audited")
        if cascade is None or cascade["status"] != "done":
            out.problems.append(f"the cascade didn't finish: {cascade['status'] if cascade else 'none queued'}")
        cards = client.get(f"{API}/datasets/{ds_id}/cards").json()
        out.outdated_cards = sum(c["status"] == "outdated" for c in cards if c["kind"] == "widget")
        out.overview = next((c["status"] for c in cards if c["kind"] == "overview"), "none")
        if out.outdated_cards and out.overview == "ready":
            out.problems.append("the overview stayed ready while cards it reads went outdated")
        if out.audited:
            out.problems.append(f"the cascade's audit found {out.audited} ready card(s) whose numbers may not hold")
        dataset = db.execute("SELECT * FROM datasets WHERE id = ?", (ds_id,)).fetchone()
        again = trust.audit(db, None, dataset)
        if again:
            out.problems.append(f"audit() found {again} ready card(s) whose numbers may not hold")
        built = exporter.build(settings, db, client.app.state.duckdb, dataset, exporter.NotebookOptions())
        md = [c.source for c in built.nb.cells if c.cell_type == "markdown"]
        out.notebook_notes = sum("*Out of date (" in m for m in md)
        out.notes_expected = sum(1 for c in cards if c["status"] != "ready")
        if out.notebook_notes < out.notes_expected:
            out.problems.append(f"the notebook notes {out.notebook_notes} of {out.notes_expected} cards that aren't ready")
    finally:
        client.put(f"{API}/me/settings", json={"story_updates": "auto"})
    return out


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
            else:
                card = None
            tally.stale = stale_reuse(client, db, app.state.settings, filename, ds_id, card["id"] if card else None)
            tally.problems += [f"stale reuse: {p}" for p in tally.stale.problems]
        finally:
            db.close()
        out.append(tally)
    return out


def report(tallies: list[Tally]) -> str:
    lines = ["| File | Cards (by the model) | Chips matching their fact | Facts re-run and holding | Text runs with numbers | "
             "Causal wording | Bad labels | Claims checked | Claims failed | Synthesis |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for t in tallies:
        lines.append(f"| {t.file} | {t.cards} ({t.by_model}) | {t.chips_ok} of {t.chips} | "
                     f"{t.facts_checked - t.facts_stale} of {t.facts_checked} | {t.text_with_numbers} | {t.causal} | "
                     f"{t.labels_bad} | {t.claims_checked} | {t.claims_failed} | {t.synthesis} |")
    stale = [t.stale for t in tallies if t.stale]
    if stale:
        lines += ["", "Stale reuse: one card of the synthesis deleted, then one cell edited under Ask first.", "",
                  "| File | Column edited | Synthesis after the delete | Overview after the edit | Cards outdated | "
                  "Notebook notes (cards not ready) | Audit after the cascade |", "|---|---|---|---|---|---|---|"]
        lines += [f"| {r.file} | {r.column or '-'} | {r.synthesis_after_delete} | {r.overview} | {r.outdated_cards} | "
                  f"{r.notebook_notes} ({r.notes_expected}) | {r.audited} |" for r in stale]
    chips, ok = sum(t.chips for t in tallies), sum(t.chips_ok for t in tallies)
    problems = [p for t in tallies for p in t.problems]
    lines += ["", f"Grounded {ok} of {chips} chips. claims_checked {sum(t.claims_checked for t in tallies)}, "
                  f"claims_failed {sum(t.claims_failed for t in tallies)}.",
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
