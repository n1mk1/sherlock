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


def resolve(db: sqlite3.Connection, dataset_id: str, entities: list[dict], columns: list[str]) -> dict:
    """`{columns: {text: column}, values: {text: [column, value]}, widgets: {text: widget_id}, unresolved: [text]}`."""
    out = {"columns": {}, "values": {}, "widgets": {}, "unresolved": []}
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
    return out
