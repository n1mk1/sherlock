"""Replay (TRD §7.8, Implementation Plan D5.5): re-apply a chain of steps on an earlier version.

Undo of a step that later steps build on starts from the latest version whose effective chain is a
prefix of the new chain, then re-applies the remaining steps in order:
- an edit batch re-applies its stored edit list by `_row_id`, typed to the columns as they are now;
- the typing step re-runs its DuckDB statement;
- a cleaning step re-runs its notebook code (its own code plus the scope it ran with) in the sandbox.

Each re-applied step must run, keep every row (cleaning steps) and leave `_row_id` unique, or the
replay stops with a `ReplayError` naming the step. Each replayed step gets fresh lineage rows for
the new version, so marks and cell history follow the replayed data.
"""

import json
import re
import shutil
import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from sherlock.profile import typing as typing_step
from sherlock.sandbox import runner as sandbox
from sherlock.steps.commit import Context, StepSpec, _lineage_rows
from sherlock.steps.diff import check_version_file, diff_versions
from sherlock.storage import sql_path

TYPING_SQL = re.compile(r'^result = duckdb\.sql\("""\n(.*)\n"""\)\.df\(\)\s*$', re.S)


class ReplayError(Exception):
    def __init__(self, step: sqlite3.Row, reason: str):
        super().__init__(reason)
        self.step_id = step["id"]
        self.step_no = step["no"]
        self.reason = reason


@dataclass
class Replayed:
    """One re-applied step: its lineage for the new version and, for edit batches, the cells it edited."""
    step_id: str
    lineage: list[tuple] = field(default_factory=list)
    edited_cells: list[tuple[int, str]] = field(default_factory=list)


def _types(path: Path) -> dict[str, str]:
    conn = duckdb.connect(":memory:")
    try:
        return {r[0]: str(r[1]) for r in conn.execute(f"DESCRIBE SELECT * FROM read_parquet({sql_path(path)})").fetchall()}
    finally:
        conn.close()


def _row_ids(path: Path) -> set[int]:
    conn = duckdb.connect(":memory:")
    try:
        return {r[0] for r in conn.execute(f"SELECT _row_id FROM read_parquet({sql_path(path)})").fetchall()}
    finally:
        conn.close()


def _edit(ctx: Context, step: sqlite3.Row, old: Path, out: Path) -> dict:
    """Re-apply an edit batch. Returns the lineage overrides (invalid values keep their text)."""
    from sherlock.rows.edits import EditBatch, Prepared, produce_edit, type_value

    stored = json.loads(step["edits_json"] or "{}")
    types = _types(old)
    ids = _row_ids(old)
    user = {c: t for c, t in types.items() if c not in ("_row_id", "_quarantine_reason")}
    prepared = Prepared()
    for e in stored.get("edits", []):
        if e["column"] not in user:
            raise ReplayError(step, f"it edits the column {e['column']}, which no longer exists")
        if e["row_id"] not in ids:
            raise ReplayError(step, f"it edits row {e['row_id']}, which no longer exists")
        prepared.edits.append((e["row_id"], e["column"], type_value(e.get("value"), user[e["column"]])))
    for r in stored.get("restore_row_ids", []):
        if r not in ids:
            raise ReplayError(step, f"it restores row {r}, which no longer exists")
    for r in stored.get("new_rows", []):
        if r["row_id"] in ids:
            raise ReplayError(step, f"the row it added ({r['row_id']}) already exists")
        unknown = [c for c in r["cells"] if c not in user]
        if unknown:
            raise ReplayError(step, f"a row it added has the column {unknown[0]}, which no longer exists")
        prepared.new_rows.append((r["row_id"], {c: type_value(v, user[c]) for c, v in r["cells"].items()}))
    batch = EditBatch(
        base_version=1,
        restore_row_ids=stored.get("restore_row_ids", []),
        deleted_row_ids=[r for r in stored.get("deleted_row_ids", []) if r in ids],  # already gone is fine
    )
    produce_edit(ctx.settings, batch, prepared, types)(old, out)
    overrides = {(r, c): (t.invalid_text, "invalid") for r, c, t in prepared.edits if t.invalid_text is not None}
    for row_id, cells in prepared.new_rows:
        overrides.update({(row_id, c): (t.invalid_text, "invalid") for c, t in cells.items() if t.invalid_text is not None})
    return overrides


def _typing(ctx: Context, step: sqlite3.Row, old: Path, out: Path) -> None:
    match = TYPING_SQL.match(step["code"] or "")
    if match is None:
        raise ReplayError(step, "its statement couldn't be read back")
    try:
        typing_step.produce(match.group(1), ctx.settings)(old, out)
    except duckdb.Error as exc:
        raise ReplayError(step, f"its statement failed: {str(exc).splitlines()[0]}") from exc


def _clean(ctx: Context, dataset: sqlite3.Row, step: sqlite3.Row, old: Path, out: Path) -> None:
    code = step["notebook_code"].rstrip()
    if code.endswith("df = result"):
        code = code[: -len("df = result")].rstrip()
    r = sandbox.execute(ctx.settings, code + "\n", old, out, db=ctx.db, dataset_id=dataset["id"])
    if not r.ok:
        raise ReplayError(step, f"its code failed on the replayed data ({r.error or 'unknown error'})")


def apply(ctx: Context, dataset: sqlite3.Row, step: sqlite3.Row, old: Path, out: Path) -> Replayed:
    """Re-apply one step from `old` to `out` and check the result."""
    overrides: dict = {}
    if step["kind"] == "edit":
        overrides = _edit(ctx, step, old, out)
    elif step["kind"] == "clean" and step["created_by"] == "system":
        _typing(ctx, step, old, out)
    elif step["kind"] == "clean":
        _clean(ctx, dataset, step, old, out)
    else:
        raise ReplayError(step, f"a {step['kind']} step can't be replayed")
    try:
        check_version_file(out)
    except ValueError as exc:
        raise ReplayError(step, str(exc)) from exc
    diff = diff_versions(old, out)
    if step["kind"] != "edit" and (diff.added_row_ids or diff.deleted_row_ids):
        raise ReplayError(step, "it added or removed rows when replayed")
    spec = StepSpec(kind=step["kind"], summary="", created_by=step["created_by"], notebook_code="-",
                    gate=step["gate"], cell_overrides=overrides)
    lineage = _lineage_rows(diff.lineage, spec)
    edited = [(r[0], r[1]) for r in lineage if r[1] != "_row"] if step["kind"] == "edit" else []
    return Replayed(step["id"], lineage, edited)


def replay(ctx: Context, dataset: sqlite3.Row, folder: Path, base: Path, steps: list[sqlite3.Row],
           final: Path) -> list[Replayed]:
    """Re-apply `steps` in order on the version file `base`; the result is written to `final`.
    Intermediate files are removed; on failure nothing is left behind and `ReplayError` is raised."""
    work = folder / "versions" / f".replay_{uuid.uuid4().hex}"
    work.mkdir(parents=True)
    done: list[Replayed] = []
    try:
        current = base
        for i, step in enumerate(steps):
            out = work / f"{i}.parquet"
            done.append(apply(ctx, dataset, step, current, out))
            current = out
        final.unlink(missing_ok=True)
        shutil.copyfile(current, final)
        return done
    finally:
        shutil.rmtree(work, ignore_errors=True)
