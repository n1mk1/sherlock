"""Edit batches (TRD §4.3, App Flow §8.2): one Save is one `edit` step and one new version.

Values arrive as text (or JSON scalars) and are typed to the column's type. A value that doesn't
parse as that type is saved as an empty cell flagged `invalid`, with the text kept in lineage
(App Flow §8.2: "invalid values are saved but flagged"). New rows take fresh `_row_id`s from
`next_row_id`; deletions are real deletions; restores clear `_quarantine_reason`.
"""

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
from pydantic import BaseModel, ConfigDict, Field

from sherlock.config import Settings
from sherlock.errors import ApiError
from sherlock.rows.query import ident
from sherlock.steps.commit import Context, StepSpec, commit_step, conflict, current_version_row
from sherlock.steps.notebook import render_edit_batch, typed
from sherlock.storage import dataset_dir, new_duckdb, sql_path

SYSTEM = ("_row_id", "_quarantine_reason")
MAX_EDITS = 100_000
INT_BITS = {"TINYINT": 8, "SMALLINT": 16, "INTEGER": 32, "BIGINT": 64, "HUGEINT": 128}


class CellEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    row_id: int
    column: str
    value: str | int | float | bool | None = None


class NewRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    temp_id: str | int
    cells: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class EditBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_version: int = Field(ge=1)
    edits: list[CellEdit] = Field(default_factory=list, max_length=MAX_EDITS)
    new_rows: list[NewRow] = Field(default_factory=list, max_length=MAX_EDITS)
    restore_row_ids: list[int] = Field(default_factory=list)
    deleted_row_ids: list[int] = Field(default_factory=list)
    run_cleaning_on_new_rows: bool = False


@dataclass
class Typed:
    value: object
    invalid_text: str | None = None  # set when the text didn't parse as the column's type


@dataclass
class Prepared:
    edits: list[tuple[int, str, Typed]] = field(default_factory=list)
    new_rows: list[tuple[int, dict[str, Typed]]] = field(default_factory=list)
    temp_ids: dict[str, int] = field(default_factory=dict)


def _is_text_type(dtype: str) -> bool:
    return dtype.upper() in ("VARCHAR", "TEXT") or dtype.upper().startswith("VARCHAR")


def type_value(value, dtype: str) -> Typed:
    if value is None or (isinstance(value, str) and value.strip() == ""):
        return Typed(None)
    text = str(value).lower() if isinstance(value, bool) else str(value)
    if _is_text_type(dtype):
        return Typed(text)
    if dtype.upper() == "BOOLEAN":
        word = text.strip().lower()
        if word in ("true", "t", "yes", "y", "1"):
            return Typed(True)
        if word in ("false", "f", "no", "n", "0"):
            return Typed(False)
        return Typed(None, text)
    result = typed(text.strip(), dtype)
    if isinstance(result, str):  # `typed` keeps text it couldn't convert
        return Typed(None, text)
    bits = INT_BITS.get(dtype.upper())
    if bits and isinstance(result, float):
        return Typed(None, text)  # 3.5 in an integer column
    if bits and not -(2 ** (bits - 1)) <= result < 2 ** (bits - 1):
        return Typed(None, text)  # doesn't fit the column's integer type
    return Typed(result)


def _literal_for_duck(t: Typed):
    v = t.value
    if hasattr(v, "to_pydatetime"):
        return v.to_pydatetime()
    return v


def _check_ids(conn: duckdb.DuckDBPyConnection, ids: set[int], what: str) -> None:
    if not ids:
        return
    found = {r[0] for r in conn.execute("SELECT _row_id FROM t WHERE list_contains(?, _row_id)", [sorted(ids)]).fetchall()}
    missing = sorted(ids - found)
    if missing:
        raise ApiError(422, "invalid", f"{what}: row {missing[0]} doesn't exist in this version")


def prepare(batch: EditBatch, types: dict[str, str], next_row_id: int, conn: duckdb.DuckDBPyConnection) -> Prepared:
    user_columns = {c: t for c, t in types.items() if c not in SYSTEM}
    if not (batch.edits or batch.new_rows or batch.restore_row_ids or batch.deleted_row_ids):
        raise ApiError(422, "invalid", "There's nothing to save.")
    prepared = Prepared()
    for e in batch.edits:
        if e.column not in user_columns:
            raise ApiError(422, "invalid", f"edits: unknown column {e.column!r}")
        prepared.edits.append((e.row_id, e.column, type_value(e.value, user_columns[e.column])))
    deleted = set(batch.deleted_row_ids)
    _check_ids(conn, {e.row_id for e in batch.edits} | set(batch.restore_row_ids) | deleted, "rows")
    if deleted & {e.row_id for e in batch.edits}:
        raise ApiError(422, "invalid", "edits: a row can't be edited and deleted in the same save")
    row_id = next_row_id
    for r in batch.new_rows:
        unknown = [c for c in r.cells if c not in user_columns]
        if unknown:
            raise ApiError(422, "invalid", f"new_rows: unknown column {unknown[0]!r}")
        prepared.temp_ids[str(r.temp_id)] = row_id
        prepared.new_rows.append((row_id, {c: type_value(v, user_columns[c]) for c, v in r.cells.items()}))
        row_id += 1
    return prepared


def produce_edit(settings: Settings, batch: EditBatch, prepared: Prepared, types: dict[str, str]):
    """The `produce` for commit_step: apply the batch to the current version with DuckDB."""
    def produce(old: Path, out: Path) -> None:
        conn = new_duckdb(settings)
        try:
            conn.execute(f"CREATE TABLE t AS SELECT * FROM read_parquet({sql_path(old)})")
            by_column: dict[str, list[tuple[int, object]]] = {}
            for row_id, column, t in prepared.edits:
                by_column.setdefault(column, []).append((row_id, _literal_for_duck(t)))
            for column, pairs in by_column.items():
                conn.execute(f"CREATE OR REPLACE TEMP TABLE e (row_id BIGINT, v {types[column]})")
                conn.executemany("INSERT INTO e VALUES (?, ?)", pairs)
                conn.execute(f"UPDATE t SET {ident(column)} = e.v FROM e WHERE t._row_id = e.row_id")
            if batch.restore_row_ids:
                conn.execute("UPDATE t SET _quarantine_reason = NULL WHERE list_contains(?, _row_id)",
                             [sorted(set(batch.restore_row_ids))])
            for row_id, cells in prepared.new_rows:
                names = ["_row_id", "_quarantine_reason", *cells]
                values = [row_id, None, *[_literal_for_duck(t) for t in cells.values()]]
                conn.execute(
                    f"INSERT INTO t ({', '.join(ident(n) for n in names)}) VALUES ({', '.join('?' for _ in names)})",
                    values,
                )
            if batch.deleted_row_ids:
                conn.execute("DELETE FROM t WHERE list_contains(?, _row_id)", [sorted(set(batch.deleted_row_ids))])
            conn.execute(f"COPY (SELECT * FROM t ORDER BY _row_id) TO {sql_path(out)} (FORMAT PARQUET, COMPRESSION ZSTD)")
        finally:
            conn.close()
    return produce


def summary_of(prepared: Prepared, batch: EditBatch, how: str = "by hand") -> str:
    parts = []
    if prepared.edits:
        n = len(prepared.edits)
        parts.append(f"edited {n} cell{'s' if n != 1 else ''}")
    if prepared.new_rows:
        n = len(prepared.new_rows)
        parts.append(f"added {n} row{'s' if n != 1 else ''}")
    if batch.deleted_row_ids:
        n = len(set(batch.deleted_row_ids))
        parts.append(f"deleted {n} row{'s' if n != 1 else ''}")
    if batch.restore_row_ids:
        n = len(set(batch.restore_row_ids))
        parts.append(f"restored {n} row{'s' if n != 1 else ''}")
    text = ", ".join(parts)
    return text[0].upper() + text[1:] + " " + how


def conflicts(
    settings: Settings, folder: Path, base: sqlite3.Row, current: sqlite3.Row, batch: EditBatch
) -> list[dict]:
    """Edited cells whose value changed between the batch's base version and the current one."""
    if not batch.edits:
        return []
    conn = duckdb.connect(":memory:")
    try:
        conn.execute(f"CREATE VIEW b AS SELECT * FROM read_parquet({sql_path(folder / base['parquet_path'])})")
        conn.execute(f"CREATE VIEW c AS SELECT * FROM read_parquet({sql_path(folder / current['parquet_path'])})")
        current_cols = {r[0] for r in conn.execute("DESCRIBE c").fetchall()}
        base_cols = {r[0] for r in conn.execute("DESCRIBE b").fetchall()}
        out = []
        for e in batch.edits:
            if e.column not in current_cols or e.column not in base_cols:
                out.append({"row_id": e.row_id, "column": e.column, "mine": e.value, "theirs": None})
                continue
            q = ident(e.column)
            row = conn.execute(
                f"SELECT b.{q}::VARCHAR, c.{q}::VARCHAR FROM b FULL JOIN c USING (_row_id) WHERE _row_id = ?",
                [e.row_id],
            ).fetchone()
            if row is None or row[0] != row[1]:
                out.append({"row_id": e.row_id, "column": e.column, "mine": e.value,
                            "theirs": None if row is None else row[1]})
        return out
    finally:
        conn.close()


def save(ctx: Context, dataset: sqlite3.Row, batch: EditBatch, how: str = "by hand") -> dict:
    """Commit the batch as one `edit` step. A stale `base_version` is `409` with the conflicts."""
    folder = dataset_dir(ctx.settings, dataset["user_id"], dataset["id"])
    current = current_version_row(ctx.db, dataset["id"])
    if batch.base_version != current["version"]:
        base = ctx.db.execute(
            "SELECT * FROM versions WHERE dataset_id = ? AND version = ?", (dataset["id"], batch.base_version)
        ).fetchone()
        found = conflicts(ctx.settings, folder, base, current, batch) if base is not None else []
        raise conflict(
            f"The data changed since you started (now version {current['version']}). Review the conflicts and save again.",
            current_version=current["version"], conflicts=found,
        )
    conn = duckdb.connect(":memory:")
    try:
        conn.execute(f"CREATE TABLE t AS SELECT _row_id FROM read_parquet({sql_path(folder / current['parquet_path'])})")
        types = {c["name"]: c["type"] for c in json.loads(current["columns_json"])}
        prepared = prepare(batch, types, dataset["next_row_id"], conn)
    finally:
        conn.close()

    overrides = {(r, c): (t.invalid_text, "invalid") for r, c, t in prepared.edits if t.invalid_text is not None}
    for row_id, cells in prepared.new_rows:
        overrides.update({(row_id, c): (t.invalid_text, "invalid") for c, t in cells.items() if t.invalid_text is not None})
    code = render_edit_batch(
        [{"row_id": r, "column": c, "value": t.value} for r, c, t in prepared.edits],
        [{"row_id": r, "cells": {c: t.value for c, t in cells.items()}} for r, cells in prepared.new_rows],
        batch.deleted_row_ids,
        batch.restore_row_ids,
        types,
    )
    stored = batch.model_dump()
    stored["new_rows"] = [
        {"temp_id": r.temp_id, "row_id": prepared.temp_ids[str(r.temp_id)], "cells": r.cells} for r in batch.new_rows
    ]
    spec = StepSpec(
        kind="edit", summary=summary_of(prepared, batch, how), created_by="user", notebook_code=code,
        column_targets=sorted({c for _, c, _ in prepared.edits}), edits=stored, gate="user",
        cell_overrides=overrides,
    )
    step, version = commit_step(ctx, dataset["id"], batch.base_version, spec, produce_edit(ctx.settings, batch, prepared, types))
    return {"step": step, "version": version, "new_row_ids": prepared.temp_ids}
