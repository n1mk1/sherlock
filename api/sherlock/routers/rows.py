"""Rows (TRD §4.3): the CSV tab's row pages, cell history, edit batches, find, column values and
the CSV download."""

import csv
import io
import json
import re
import sqlite3
from collections.abc import Iterator

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import StreamingResponse

from sherlock.db.connection import get_db
from sherlock.errors import not_found
from sherlock.ownership import owned_dataset
from sherlock.rows import query as rq
from sherlock.rows.edits import EditBatch, save
from sherlock.steps import lineage
from sherlock.steps.commit import Context
from sherlock.storage import dataset_dir

router = APIRouter(tags=["rows"])
FIND_FIRST = 100
FIND_ALL = 10_000
CSV_CHUNK = 5000


def _version_row(db: sqlite3.Connection, dataset: sqlite3.Row, version: int | None) -> sqlite3.Row:
    version = version or dataset["current_version"]
    row = db.execute(
        "SELECT * FROM versions WHERE dataset_id = ? AND version = ?", (dataset["id"], version)
    ).fetchone()
    if row is None:
        raise not_found(f"Version {version} not found")
    return row


def _connection(request: Request, dataset: sqlite3.Row, vrow: sqlite3.Row):
    folder = dataset_dir(request.app.state.settings, dataset["user_id"], dataset["id"])
    return request.app.state.duckdb.connection(dataset["id"], vrow["version"], folder / vrow["parquet_path"])


def _selection(db: sqlite3.Connection, dataset_id: str, selection_id: str, where: rq.Where) -> None:
    sel = db.execute("SELECT * FROM selections WHERE id = ? AND dataset_id = ?", (selection_id, dataset_id)).fetchone()
    if sel is None:
        raise not_found("Selection not found")
    if sel["row_ids_json"]:
        where.add("list_contains(?, _row_id)", json.loads(sel["row_ids_json"]))
    elif sel["predicate"]:
        where.add(f"({sel['predicate']})")  # validated when the selection was made (TRD §4.3)


@router.get("/datasets/{dataset_id}/rows")
def get_rows(
    request: Request,
    version: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=rq.MAX_LIMIT),
    sort: str | None = None,
    filter: str | None = None,
    view: str = Query(default="all"),
    selection: str | None = None,
    dataset: sqlite3.Row = Depends(owned_dataset),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """A page of rows with their cell marks. Quarantined rows are included and marked."""
    if view not in rq.VIEWS:
        raise rq.invalid(f"view must be one of {', '.join(rq.VIEWS)}")
    vrow = _version_row(db, dataset, version)
    steps = lineage.chain(db, dataset["id"], vrow["version"])
    with _connection(request, dataset, vrow) as conn:
        types = rq.describe(conn)
        user_types = {c: t for c, t in types.items() if c not in rq.SYSTEM}
        where = rq.Where([], [])
        rq.apply_filter(where, filter, user_types)
        if view == "changed":
            where.add("list_contains(?, _row_id)", lineage.marked_row_ids(db, dataset["id"], steps, flagged_only=False))
        elif view == "flagged":
            ids = lineage.marked_row_ids(db, dataset["id"], steps, flagged_only=True)
            where.add("(_quarantine_reason IS NOT NULL OR list_contains(?, _row_id))", ids)
        elif view == "missing":
            if user_types:
                where.add("(" + " OR ".join(f"{rq.ident(c)} IS NULL" for c in user_types) + ")")
        if selection:
            _selection(db, dataset["id"], selection, where)
        order = rq.parse_sort(sort, list(user_types))
        total, names, rows = rq.page(conn, where, order, offset, limit)
    row_ids = [r[names.index("_row_id")] for r in rows]
    marks = lineage.cell_marks(db, dataset["id"], steps, row_ids)
    out = []
    for r in rows:
        record = dict(zip(names, r))
        rid = record["_row_id"]
        reason = record["_quarantine_reason"]
        out.append({
            "_row_id": rid,
            "cells": {c: rq.json_value(record[c]) for c in user_types},
            "marks": marks.get(rid, {}),
            "quarantined": reason is not None,
            "quarantine_reason": reason,
        })
    return {
        "version": vrow["version"],
        "total": total,
        "columns": [{"name": c, "type": t} for c, t in user_types.items()],
        "rows": out,
    }


@router.get("/datasets/{dataset_id}/cells/{row_id}/{column}/history")
def cell_history(
    row_id: int,
    column: str,
    version: int | None = Query(default=None, ge=1),
    dataset: sqlite3.Row = Depends(owned_dataset),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    vrow = _version_row(db, dataset, version)
    steps = lineage.chain(db, dataset["id"], vrow["version"])
    return {"entries": lineage.cell_history(db, dataset["id"], steps, row_id, column)}


@router.post("/datasets/{dataset_id}/edits", status_code=status.HTTP_201_CREATED)
def post_edits(
    body: EditBatch,
    request: Request,
    dataset: sqlite3.Row = Depends(owned_dataset),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """One Save: one `edit` step and one new version, or `409` with the conflicts."""
    ctx = Context(request.app.state.settings, db, request.app.state.duckdb, request.app.state.bus)
    return save(ctx, dataset, body)


@router.get("/datasets/{dataset_id}/find")
def find(
    request: Request,
    q: str = Query(min_length=1, max_length=500),
    regex: bool = False,
    column: str | None = None,
    selection: str | None = None,
    all: bool = False,
    dataset: sqlite3.Row = Depends(owned_dataset),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Matches on the cells' text (case-insensitive), in row order."""
    if regex:
        try:
            re.compile(q)
        except re.error as exc:
            raise rq.invalid(f"q: not a valid regular expression ({exc})") from None
    vrow = _version_row(db, dataset, None)
    with _connection(request, dataset, vrow) as conn:
        types = {c: t for c, t in rq.describe(conn).items() if c not in rq.SYSTEM}
        if column is not None and column not in types:
            raise rq.invalid(f"column: unknown column {column!r}")
        columns = [column] if column else list(types)
        if not columns:
            return {"count": 0, "first_matches": []}
        where = rq.Where([], [])
        if selection:
            _selection(db, dataset["id"], selection, where)
        test = "regexp_matches({col}, ?, 'i')" if regex else "{col} ILIKE ?"
        needle = q if regex else "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        if not regex:
            test += " ESCAPE '\\'"
        parts, params = [], []
        for position, c in enumerate(columns):
            parts.append(
                f"SELECT _row_id, {position} AS pos, CAST({rq.ident(c)} AS VARCHAR) AS value FROM t "
                f"WHERE {where.clause()} AND {test.format(col=f'CAST({rq.ident(c)} AS VARCHAR)')}"
            )
            params += [*where.params, needle]
        union = " UNION ALL ".join(parts)
        count = conn.execute(f"SELECT count(*) FROM ({union})", params).fetchone()[0]
        limit = FIND_ALL if all else FIND_FIRST
        matches = conn.execute(f"SELECT * FROM ({union}) ORDER BY _row_id, pos LIMIT {limit}", params).fetchall()
    first = [{"row_id": r[0], "column": columns[r[1]], **({"value": r[2]} if all else {})} for r in matches]
    return {"count": count, "first_matches": first}


@router.get("/datasets/{dataset_id}/columns/{column}/values")
def column_values(
    column: str,
    prefix: str = "",
    limit: int = Query(default=50, ge=1, le=500),
    dataset: sqlite3.Row = Depends(owned_dataset),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Distinct values with counts from the value index (dimension and target-like columns)."""
    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = db.execute(
        "SELECT value, count FROM value_index WHERE dataset_id = ? AND column = ? AND value LIKE ? ESCAPE '\\' "
        "ORDER BY count DESC, value LIMIT ?",
        (dataset["id"], column, escaped + "%", limit),
    ).fetchall()
    return {"values": [{"value": r[0], "count": r[1]} for r in rows]}


@router.get("/datasets/{dataset_id}/export.csv")
def export_csv(
    request: Request,
    version: int | None = Query(default=None, ge=1),
    dataset: sqlite3.Row = Depends(owned_dataset),
    db: sqlite3.Connection = Depends(get_db),
) -> StreamingResponse:
    """The version's data: every row the grid shows (quarantined rows too), user columns only, in
    `_row_id` order, as UTF-8 CSV (PRD CSV-12)."""
    vrow = _version_row(db, dataset, version)
    with _connection(request, dataset, vrow) as conn:
        types = {c: t for c, t in rq.describe(conn).items() if c not in rq.SYSTEM}
        cols = ", ".join(rq.ident(c) for c in types) or "NULL"
        rows = conn.execute(f"SELECT {cols} FROM t ORDER BY _row_id").fetchall()

    def chunks() -> Iterator[str]:
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(list(types))
        for i, r in enumerate(rows, 1):
            writer.writerow(["" if v is None else rq.json_value(v) for v in r])
            if i % CSV_CHUNK == 0:
                yield buf.getvalue()
                buf.seek(0)
                buf.truncate()
        yield buf.getvalue()

    stem = re.sub(r"\.(csv|tsv|txt)$", "", dataset["name"].replace(" (sample)", ""), flags=re.I)
    filename = re.sub(r'[^A-Za-z0-9._-]+', "_", f"{stem}-v{vrow['version']}.csv")
    return StreamingResponse(
        chunks(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
