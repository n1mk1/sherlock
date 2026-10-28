"""Grounding (docs/plans/tavily.md §3.2): the first step of the `review_issues` job. Tavily finds the file's
data dictionary and explains its cryptic column names, so the columns carry a meaning and a source before
anything is cleaned or suggested.

1. One `search` for the dataset's column descriptions, by its column names (`search_query`).
2. The top one or two results go to `read_dictionary(kind="found")`: extract with the column names as the
   query, Super maps the excerpts to columns, and the notes are stored as `found` (a user's own dictionary
   still wins, see `notes_for`). The excerpts come back for the suggested checks.
3. Up to four columns still without a note whose names look like codes (`looks_like_code`: a rule, not the
   model) get `column_meaning`: one search each, Super writes a cited sentence, stored as a `web` note.
   The quotes those notes cite come back as excerpts too (`_quoted`).

What goes out is column names and fixed phrases, never a cell value and never the file's name, and
`check_query` runs on the search before it is sent. Tavily is retrieval only (`web/client.py`).

The budget is at most nine Tavily calls a run (`MAX_CALLS`), and grounding is skipped when the user has
fewer than five left this hour (`MIN_CALLS`), so chat keeps its share of the cap.

Every failure fails soft: no key, a timeout, a refused query, the model out of budget or an unusable reply
is logged, and `ground` returns what it has (nothing at worst). Grounding never blocks the review.

It runs once per dataset. The marker is the dataset's `ground_search` web call in `llm_calls` (kept
forever, cache hits included, written only when the search worked, so a failed run is tried again): the
dataset counts as grounded once it has one. Later runs ground only the columns that weren't in the newest
version made before that search, so a column a step added is looked up and the rest aren't. A dataset
whose columns already have a `dictionary` or `found` note (the user linked one) isn't grounded at all.
"""

import dataclasses
import json
import logging
import re
import sqlite3

from sherlock.agent import web as aw
from sherlock.config import Settings
from sherlock.jobs.events import EventBus, emit
from sherlock.llm.client import BudgetExceeded, CallScope, LLMClient, LLMUnavailable, StructuredOutputError
from sherlock.web.client import WebClient, WebUnavailable

log = logging.getLogger("sherlock.ground")

MAX_CALLS = 9          # Tavily calls in one run, cached or not
MIN_CALLS = 5          # fewer than this left of the hour's cap: skip, so chat keeps working
READ_CALLS = 5         # of them, the search and its dictionary reads (at most four); the rest go to cryptic columns
MAX_READS = 2          # result pages read as a data dictionary
MAX_CRYPTIC = 4        # columns looked up one by one
# "Data dictionary" or "codebook" in the query finds word dictionaries (a live search for a file's column
# names scored only dictionary entries for one of the names, all under `MIN_SCORE`); asking for a dataset's
# column descriptions finds the pages that document it.
PREFIX = "dataset columns "
SUFFIX = " column descriptions"
MAX_QUERY = 400        # Tavily's advice for a query

# Words a column is plainly named by: never looked up, however short or consonant-heavy.
COMMON = frozenset("""
id ids uid uuid key no num number nbr name names first last full middle sur age sex gender date time datetime
timestamp day days week weeks month months year years hour minute second city state country zip zipcode postcode
address street region area price cost fee fare amount total sum count mean avg average min max rate ratio share
percent score rank grade level type kind class group category tag label status flag note notes comment text title
description desc email phone mobile url link image width height length depth weight size volume speed distance
income salary wage tax profit loss sales sale order orders item items product products customer client user users
account balance payment currency lat lon lng latitude longitude start end begin from to open close high low
value values code index row col column parent child left right top bottom source target result output input
unit units quantity stock team teams player players home away born birth death died alive active live current
previous next old new
""".split())
SPLIT = re.compile(r"[^0-9A-Za-z]+")
CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])")
LETTER_AND_NUMBER = re.compile(r"(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9]+$")
SHORT_CODE = re.compile(r"^(?:[A-Za-z]\d+|\d+[A-Za-z])$")   # q1, x2, 3d: a quarter or an axis, not a code book entry
VOWELS = frozenset("aeiou")
SHORT = 6              # letters; a longer plain word is a word


def _tokens(name: str) -> list[str]:
    return [t for part in SPLIT.split(name) for t in CAMEL.split(part) if t]


def looks_like_code(name: str, caps_count: bool = True) -> bool:
    """Whether a column's name looks like a code a codebook would explain, by rule (not the model): a name made
    of common words ("customer_name", "age") never does; otherwise one of its words does when it
    mixes letters and digits ("ICD10"), is a short all-capitals abbreviation ("SKU"; only when `caps_count`,
    that is, the file's other names aren't all in capitals), has no vowel ("qty") or hardly any ("pclass")."""
    for tok in _tokens(name):
        low = tok.lower()
        if low in COMMON or tok.isdigit() or SHORT_CODE.match(tok):
            continue
        if LETTER_AND_NUMBER.match(tok):
            return True
        if not tok.isalpha() or not 2 <= len(tok) <= SHORT:
            continue
        vowels = sum(ch in VOWELS for ch in low)
        if vowels == 0 or vowels / len(tok) <= 0.25:
            return True
        if caps_count and tok.isupper() and len(tok) >= 2:
            return True
    return False


def cryptic(columns: list[str], skip: set[str] = frozenset()) -> list[str]:
    """The columns whose names look like codes, in file order, without those in `skip`, at most `MAX_CRYPTIC`."""
    lettered = [c for c in columns if any(ch.isalpha() for ch in c)]
    caps_count = not (lettered and all(c == c.upper() for c in lettered))
    return [c for c in columns if c not in skip and looks_like_code(c, caps_count)][:MAX_CRYPTIC]


def search_query(columns: list[str]) -> str:
    """The column names that fit a query, and the fixed words that make it a search for a dictionary."""
    room = MAX_QUERY - len(PREFIX) - len(SUFFIX)
    names: list[str] = []
    for c in columns:
        if len(" ".join([*names, c])) > room:
            break
        names.append(c)
    if not names and columns:
        names = [columns[0][:room]]
    return PREFIX + " ".join(names) + SUFFIX


class _Meter:
    """The web client, counting the calls made through it: a run stops at its limit with a soft failure."""

    def __init__(self, web: WebClient, limit: int) -> None:
        self.web, self.limit, self.used = web, limit, 0

    @property
    def enabled(self) -> bool:
        return self.web.enabled

    def _spend(self) -> None:
        if self.used >= self.limit:
            raise WebUnavailable("rate", "the grounding budget is spent")
        self.used += 1

    def search(self, *args, **kwargs):
        self._spend()
        return self.web.search(*args, **kwargs)

    def extract(self, *args, **kwargs):
        self._spend()
        return self.web.extract(*args, **kwargs)

    def map(self, *args, **kwargs):
        self._spend()
        return self.web.map(*args, **kwargs)


def _noted(db: sqlite3.Connection, dataset_id: str) -> tuple[set[str], set[str]]:
    """(columns with a note of any kind, columns with a dictionary's or a found dictionary's note)."""
    notes = aw.notes_for(db, dataset_id)
    return ({n["column"] for n in notes}, {n["column"] for n in notes if n["kind"] in ("dictionary", "found")})


def pending(db: sqlite3.Connection, dataset_id: str, columns: list[str]) -> list[str]:
    """The columns to ground now: all of them the first time; later only those that weren't in the newest
    version made before the last grounding search; none when the user's own dictionary or a found one
    already explains the dataset."""
    noted, dictionaries = _noted(db, dataset_id)
    last = db.execute("SELECT max(created_at) FROM llm_calls WHERE role = 'web' AND purpose = 'ground_search' "
                      "AND ok = 1 AND dataset_id = ?", (dataset_id,)).fetchone()[0]
    if last is None:
        return [] if dictionaries & set(columns) else [c for c in columns if c not in noted]
    row = (db.execute("SELECT columns_json FROM versions WHERE dataset_id = ? AND created_at <= ? ORDER BY version DESC LIMIT 1",
                      (dataset_id, last)).fetchone()
           or db.execute("SELECT columns_json FROM versions WHERE dataset_id = ? ORDER BY version LIMIT 1", (dataset_id,)).fetchone())
    known = {c["name"] for c in json.loads(row["columns_json"])} if row else set(columns)
    return [c for c in columns if c not in known and c not in noted]


def _about(column: str, card: dict) -> str:
    """What Super is told about a column besides its name: its type and example values. It reads this; Tavily
    never does (the search holds the column name only), and the file's name isn't in it."""
    entry = next((c for c in card["columns"] if c["name"] == column), {})
    examples = [str(v["value"]) for v in (entry.get("top_values") or [])[:5]] or [str(v) for v in (entry.get("sample_values") or [])[:5]]
    return f"column: {column}\ntype: {entry.get('type', 'text')}\nexamples: " + ", ".join(e[:40] for e in examples)


def _numbered(parts: list[list[dict]]) -> list[dict]:
    """Excerpts from several pages as one list, numbered from 1 again."""
    out = []
    for e in (e for part in parts for e in part):
        out.append({**e, "n": len(out) + 1})
    return out


def ground(settings: Settings, db: sqlite3.Connection, dataset: sqlite3.Row, card: dict, scope: CallScope,
           llm: LLMClient | None = None, web: WebClient | None = None, bus: EventBus | None = None) -> list[dict]:
    """Look up what the dataset's columns mean and store it as column notes. Returns the excerpts that were
    read (`[{n, url, title, text, retrieved_at}]`), for the suggested checks; `[]` when grounding is off, can't
    run (no model or web), is short of budget, was done already, or failed. Emits `notes.updated` on `bus`
    (when given) after storing any note."""
    if settings.clean_ground != "on" or (llm is None and not (settings.llm_base_url or settings.llm_mock)):
        return []
    web = web or WebClient(settings)
    if not web.enabled:
        return []
    columns = [c["name"] for c in card["columns"]]
    todo = pending(db, dataset["id"], columns)
    if not todo:
        return []
    scope = scope if scope.dataset_id else dataclasses.replace(scope, dataset_id=dataset["id"])
    left = web.calls_left(scope)
    if left is not None and left < MIN_CALLS:
        log.info("grounding skipped: %s web calls left this hour", left)
        return []
    llm = llm or LLMClient(settings)
    before = aw.notes_for(db, dataset["id"])  # a note added or rewritten is news for the header hovers
    meter = _Meter(web, READ_CALLS)
    read: list[list[dict]] = []
    try:
        _look(llm, scope, meter, db, dataset["id"], card, todo, columns, read)
    except (WebUnavailable, LLMUnavailable, BudgetExceeded, StructuredOutputError) as exc:
        log.warning("grounding stopped early: %s", exc)
    after = aw.notes_for(db, dataset["id"])
    if after != before:
        emit(db, bus, dataset["id"], dataset["user_id"], "notes.updated", {}, scope.job_id)
    read.append(_quoted(after, before, read))
    return _numbered(read)


def _quoted(after: list[dict], before: list[dict], read: list[list[dict]]) -> list[dict]:
    """The quotes this run's `web` notes were written from, as excerpts, so a check can cite them when no
    dictionary page was read: a column lookup often lands on a page that lists every column ("FLAG: … = 1 if
    the row qualifies; 0 otherwise"). Each quote once, and none a dictionary excerpt already holds."""
    seen = {e["text"] for part in read for e in part}
    out = []
    for n in after:
        if n["kind"] != "web" or n in before or not n.get("excerpt") or n["excerpt"] in seen:
            continue
        seen.add(n["excerpt"])
        out.append({"n": 0, "url": n["source_url"], "title": n.get("source_title") or n["source_url"],
                    "text": n["excerpt"], "retrieved_at": (n.get("retrieved_at") or "")[:10]})
    return out


def _look(llm, scope: CallScope, meter: _Meter, db: sqlite3.Connection, dataset_id: str, card: dict, todo: list[str],
          columns: list[str], read: list[list[dict]]) -> None:
    """Steps 1 to 3. `read` collects each page's excerpts as they come, so an early failure keeps them."""
    query = search_query(todo)
    try:
        aw.check_query(query, "", todo, aw.file_values(db, dataset_id))
    except aw.QueryRefused as exc:
        log.warning("grounding search not sent: %s", exc)
        return
    found = aw.keep(meter.search(query, scope=scope, purpose="ground_search"))
    for hit in found[:MAX_READS]:
        wanting = [c for c in todo if c not in _noted(db, dataset_id)[0]]
        if not wanting:
            break
        got = aw.read_dictionary(llm, scope, meter, db, dataset_id, hit["url"], wanting, kind="found")
        if got.get("excerpts"):
            read.append(got["excerpts"])
        if got.get("note"):
            log.info("grounding read of %s: %s", hit["url"], got["note"])
    meter.limit = MAX_CALLS
    for column in cryptic(todo, skip=_noted(db, dataset_id)[0]):
        if meter.used >= meter.limit:
            break
        aw.column_meaning(llm, scope, meter, db, dataset_id, column, columns, _about(column, card))
