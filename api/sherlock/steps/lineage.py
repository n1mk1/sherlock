"""Lineage reads (TRD §7.9): cell marks and cell history for a version, through its effective chain.

A version's effective chain lists the steps whose effects make it up. For each of those steps only
its lineage rows with the greatest `version` not above the version being read count, so undone
changes drop out and a replayed step is not counted twice.

Marks: a cell whose lineage flag is `quarantined` or `invalid` (its value didn't parse; the text is
kept in lineage) is `invalid`; a cell of a flagged step is `flagged`; any other changed cell is
`changed`. The latest step that touched the cell decides.

`changes` reads the other way, from steps to columns: what the steps after one version touched, and
whether they changed which rows or columns there are. ML outdating uses it on every new version
(TRD §7.5, PRD ML-9).
"""

import json
import sqlite3
from dataclasses import dataclass

INVALID_FLAGS = ("quarantined", "invalid")
# Impact fields that mean a step changed which rows there are, so everything is affected.
ROWS_CHANGED = ("rows_added", "rows_deleted", "quarantined", "rows_restored")


@dataclass(frozen=True)
class ChainStep:
    step_id: str
    no: int
    version: int  # the lineage version of this step that counts
    summary: str


def chain(db: sqlite3.Connection, dataset_id: str, version: int) -> list[ChainStep]:
    row = db.execute(
        "SELECT effective_step_ids_json FROM versions WHERE dataset_id = ? AND version = ?", (dataset_id, version)
    ).fetchone()
    if row is None:
        return []
    ids = json.loads(row[0])
    if not ids:
        return []
    marks = ", ".join("?" for _ in ids)
    applied = dict(db.execute(
        f"SELECT step_id, max(version) FROM lineage WHERE dataset_id = ? AND step_id IN ({marks}) AND version <= ? "
        "GROUP BY step_id",
        (dataset_id, *ids, version),
    ).fetchall())
    steps = {r["id"]: r for r in db.execute(f"SELECT id, no, summary FROM steps WHERE id IN ({marks})", ids)}
    return [ChainStep(i, steps[i]["no"], applied[i], steps[i]["summary"]) for i in ids if i in applied]


def _cte(steps: list[ChainStep]) -> tuple[str, list]:
    values = ", ".join("(?, ?, ?)" for _ in steps)
    params: list = []
    for s in steps:
        params += [s.step_id, s.version, s.no]
    return f"WITH eff(step_id, version, no) AS (VALUES {values})", params


def mark_of(flag: str | None) -> str:
    if flag in INVALID_FLAGS:
        return "invalid"
    if flag == "flagged":
        return "flagged"
    return "changed"


def cell_marks(
    db: sqlite3.Connection, dataset_id: str, steps: list[ChainStep], row_ids: list[int]
) -> dict[int, dict[str, str]]:
    """row_id → {column: mark} for the given rows."""
    if not steps or not row_ids:
        return {}
    cte, params = _cte(steps)
    ids = ", ".join("?" for _ in row_ids)
    rows = db.execute(
        f"{cte} SELECT l.row_id, l.column, l.flag FROM lineage l JOIN eff ON eff.step_id = l.step_id "
        f"AND eff.version = l.version WHERE l.dataset_id = ? AND l.column != '_row' AND l.row_id IN ({ids}) "
        "ORDER BY eff.no",
        (*params, dataset_id, *row_ids),
    ).fetchall()
    marks: dict[int, dict[str, str]] = {}
    for row_id, column, flag in rows:  # later steps overwrite earlier ones
        marks.setdefault(row_id, {})[column] = mark_of(flag)
    return marks


def marked_row_ids(db: sqlite3.Connection, dataset_id: str, steps: list[ChainStep], flagged_only: bool) -> list[int]:
    """Rows with any mark (the "only changed" view), or with a flagged or invalid cell."""
    if not steps:
        return []
    cte, params = _cte(steps)
    where = "AND (l.flag IS NOT NULL)" if flagged_only else ""
    return [r[0] for r in db.execute(
        f"{cte} SELECT DISTINCT l.row_id FROM lineage l JOIN eff ON eff.step_id = l.step_id "
        f"AND eff.version = l.version WHERE l.dataset_id = ? AND l.column != '_row' {where}",
        (*params, dataset_id),
    ).fetchall()]


def cell_history(db: sqlite3.Connection, dataset_id: str, steps: list[ChainStep], row_id: int, column: str) -> list[dict]:
    """The cell's changes in the version, oldest first."""
    if not steps:
        return []
    cte, params = _cte(steps)
    rows = db.execute(
        f"{cte} SELECT l.step_id, eff.no, l.old_value, l.new_value, l.flag FROM lineage l "
        "JOIN eff ON eff.step_id = l.step_id AND eff.version = l.version "
        "WHERE l.dataset_id = ? AND l.row_id = ? AND l.column = ? ORDER BY eff.no",
        (*params, dataset_id, row_id, column),
    ).fetchall()
    summaries = {s.step_id: s.summary for s in steps}
    return [
        {"step_id": r[0], "step_no": r[1], "old": r[2], "new": r[3], "summary": summaries[r[0]], "flag": r[4]}
        for r in rows
    ]


def changes(db: sqlite3.Connection, dataset_id: str, since: int, version: int) -> tuple[set[str], bool]:
    """(changed columns, everything affected) for the steps after `since` up to `version`."""
    cols: set[str] = set()
    everything = False
    steps = db.execute("SELECT * FROM steps WHERE dataset_id = ? AND to_version > ? AND to_version <= ?",
                       (dataset_id, since, version)).fetchall()
    for s in steps:
        ids = [s["id"]] + (json.loads(s["replayed_step_ids_json"]) if s["replayed_step_ids_json"] else [])
        for sid in ids:
            r = db.execute("SELECT * FROM steps WHERE id = ?", (sid,)).fetchone()
            cols.update(json.loads(r["column_targets_json"]))
            if json.loads(r["columns_added_json"]) or json.loads(r["columns_removed_json"]):
                everything = True
            if r["kind"] == "clean" and r["created_by"] == "system":
                everything = True  # typing (or undoing it) changes column types
            impact = json.loads(r["impact_json"])
            if any(impact.get(k) for k in ROWS_CHANGED):
                everything = True
            if r["edits_json"] and json.loads(r["edits_json"]).get("restore_row_ids"):
                everything = True
        if s["kind"] in ("undo", "redo") and s["undone_step_id"]:
            u = db.execute("SELECT * FROM steps WHERE id = ?", (s["undone_step_id"],)).fetchone()
            cols.update(json.loads(u["column_targets_json"]))
            impact = json.loads(u["impact_json"])
            # Undoing a restore quarantines those rows again, like undoing any change of rows.
            restored = bool(u["edits_json"] and json.loads(u["edits_json"]).get("restore_row_ids"))
            if any(impact.get(k) for k in ROWS_CHANGED) or restored \
                    or json.loads(u["columns_added_json"]) or json.loads(u["columns_removed_json"]) \
                    or (u["kind"] == "clean" and u["created_by"] == "system"):
                everything = True
    return cols, everything
