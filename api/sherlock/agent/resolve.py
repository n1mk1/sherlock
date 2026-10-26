"""Name and value resolution (TRD §8.1 step 3): the entities the router found → columns, category
values and widgets. Columns match exactly, then ignoring case and underscores, then by fuzzy match;
values match through the value index, exactly then fuzzily (rapidfuzz ≥ 90). There is no embedding
model in the catalog, so the embedding steps are skipped (TRD §3.5)."""

import re
import sqlite3

from rapidfuzz import fuzz, process

COLUMN_FUZZ = 85
VALUE_FUZZ = 90
WIDGET_FUZZ = 75
CLOSE_FUZZ = 70   # a name nothing resolved looks like a reference when its best match scores this (clarifications)
OPTION_FUZZ = 50  # the other options of that clarification


def _norm(text: str) -> str:
    return re.sub(r"[\s_.\-]+", "", text.lower())


def column(name: str, columns: list[str]) -> str | None:
    if name in columns:
        return name
    by_norm = {_norm(c): c for c in columns}
    if _norm(name) in by_norm:
        return by_norm[_norm(name)]
    # Whole-string similarity, not partial: "average fare" must not match "age".
    hit = process.extractOne(_norm(name), {c: _norm(c) for c in columns}, scorer=fuzz.ratio, score_cutoff=COLUMN_FUZZ)
    return hit[2] if hit else None


def value(db: sqlite3.Connection, dataset_id: str, text: str) -> tuple[str, str] | None:
    """(column, value) from the value index for a category value the user named."""
    rows = db.execute("SELECT column, value, count FROM value_index WHERE dataset_id = ?", (dataset_id,)).fetchall()
    exact = [r for r in rows if r["value"].lower() == text.lower()]
    if exact:
        best = max(exact, key=lambda r: r["count"])
        return best["column"], best["value"]
    choices = {i: r["value"].lower() for i, r in enumerate(rows)}
    hit = process.extractOne(text.lower(), choices, scorer=fuzz.token_sort_ratio, score_cutoff=VALUE_FUZZ)
    if hit is None:
        return None
    r = rows[hit[2]]
    return r["column"], r["value"]


def widget(db: sqlite3.Connection, dataset_id: str, text: str) -> sqlite3.Row | None:
    rows = db.execute("SELECT * FROM widgets WHERE dataset_id = ? AND deleted_at IS NULL", (dataset_id,)).fetchall()
    if not rows:
        return None
    hit = process.extractOne(text.lower(), {i: r["title"].lower() for i, r in enumerate(rows)},
                             scorer=fuzz.token_set_ratio, score_cutoff=WIDGET_FUZZ)
    return rows[hit[2]] if hit else None


def candidates(db: sqlite3.Connection, dataset_id: str, text: str, kind: str, columns: list[str]) -> list[tuple[str, dict]]:
    """Two or three (option, meaning) pairs for a name nothing resolved (TRD §8.1 step 3, PRD ASK-6),
    or none when the name doesn't look like a reference to this file: its best match scores under
    `CLOSE_FUZZ`. A column-like name is matched against the columns, a value-like one against the value
    index. Options scoring under `OPTION_FUZZ` fill in only when fewer than two are close."""
    if kind == "column":
        pool = {c: _norm(c) for c in columns}
        hits = process.extract(_norm(text), pool, scorer=fuzz.ratio, limit=3)
        found = [(c, {"column": c}, score) for _, score, c in hits]
    else:
        rows = db.execute("SELECT column, value, count FROM value_index WHERE dataset_id = ?", (dataset_id,)).fetchall()
        hits = process.extract(text.lower(), {i: r["value"].lower() for i, r in enumerate(rows)},
                               scorer=fuzz.token_sort_ratio, limit=6)
        found = [(rows[i]["value"], {"value": [rows[i]["column"], rows[i]["value"]]}, score) for _, score, i in hits]
        found = [f for n, f in enumerate(found) if f[0] not in {g[0] for g in found[:n]}][:3]  # one button per text
    if not found or found[0][2] < CLOSE_FUZZ:
        return []
    close = [(o, m) for o, m, score in found if score >= OPTION_FUZZ]
    out = close if len(close) >= 2 else [(o, m) for o, m, _ in found[:2]]
    return out if len(out) >= 2 else []


def widget_options(question: str, rows: list[sqlite3.Row]) -> list[tuple[str, dict]]:
    """The two or three widgets whose titles best match the message, as (title, meaning) clarification
    options; dashboard order breaks ties. None with fewer than two widgets."""
    scored = sorted(enumerate(rows), key=lambda ir: (-fuzz.token_set_ratio(question.lower(), ir[1]["title"].lower()), ir[0]))
    out, seen = [], set()
    for _, r in scored:
        if r["title"] not in seen:  # one button per title
            seen.add(r["title"])
            out.append((r["title"], {"widget": r["id"]}))
    return out[:3] if len(out) >= 2 else []


def column_options(question: str, columns: list[str], limit: int = 3) -> list[tuple[str, dict]]:
    """The columns whose names best match a word of the message, as (column, meaning) clarification
    options (file order breaks ties)."""
    words = re.findall(r"[\w.]+", question.lower()) or [""]
    score = {c: max(fuzz.ratio(_norm(w), _norm(c)) for w in words) for c in columns}
    ranked = sorted(columns, key=lambda c: (-score[c], columns.index(c)))
    return [(c, {"column": c}) for c in ranked[:limit]]


def resolve(db: sqlite3.Connection, dataset_id: str, entities: list[dict], columns: list[str]) -> dict:
    """`{columns: {text: column}, values: {text: [column, value]}, widgets: {text: widget_id}, unresolved: [text],
    unresolved_kinds: {text: kind}}`."""
    out = {"columns": {}, "values": {}, "widgets": {}, "unresolved": [], "unresolved_kinds": {}}
    for e in entities:
        text, kind = e["text"].strip(), e["kind"]
        if not text:
            continue
        if kind == "widget":
            w = widget(db, dataset_id, text)
            if w is not None:
                out["widgets"][text] = w["id"]
                continue
        if kind in ("column", "widget", "card"):
            c = column(text, columns)
            if c is not None:
                out["columns"][text] = c
                continue
        v = value(db, dataset_id, text)
        if v is not None:
            out["values"][text] = list(v)
            continue
        c = column(text, columns)
        if c is not None:
            out["columns"][text] = c
        elif kind in ("column", "value"):
            out["unresolved"].append(text)
            out["unresolved_kinds"][text] = kind
    return out
