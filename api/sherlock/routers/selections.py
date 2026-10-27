"""Row selections (TRD §4.3): the CSV tab's selected rows as a named set chat and ML can read."""

import json
import sqlite3

from fastapi import APIRouter, Body, Depends, Request, status

from sherlock.db.connection import get_db
from sherlock.db.util import new_id, now_iso
from sherlock.errors import ApiError
from sherlock.ownership import owned_dataset
from sherlock.query import compile as qc
from sherlock.query import context as qx

router = APIRouter(tags=["rows"])


@router.post("/datasets/{dataset_id}/selections", status_code=status.HTTP_201_CREATED)
def create_selection(
    request: Request,
    body: dict = Body(...),
    dataset: sqlite3.Row = Depends(owned_dataset),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """A row selection on the current version: a validated predicate or explicit `_row_id`s.
    `row_count` counts rows that aren't quarantined, which is what ML and chat use."""
    predicate, row_ids, label = body.get("predicate"), body.get("row_ids"), body.get("label")
    if (predicate is None) == (row_ids is None):
        raise ApiError(422, "invalid", "Send either a predicate or row_ids.")
    env = qx.Env(request.app.state.settings, db, request.app.state.duckdb, request.app.state.bus)
    version = dataset["current_version"]
    if predicate is not None:
        if not isinstance(predicate, str):
            raise ApiError(422, "invalid", "predicate: must be text")
        predicate = qc.validate_predicate(predicate, list(qx.user_types(env, dataset, version)))
        where = f"({predicate})"
    else:
        if not isinstance(row_ids, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in row_ids):
            raise ApiError(422, "invalid", "row_ids: must be a list of integers")
        row_ids = sorted(set(row_ids))
        where = f"_row_id IN ({', '.join(str(i) for i in row_ids)})" if row_ids else "FALSE"
    with qx.connection(env, dataset, version) as conn:
        count = conn.execute(f"SELECT count(*) FROM t WHERE _quarantine_reason IS NULL AND {where}").fetchone()[0]
    selection_id = new_id("sel")
    db.execute(
        "INSERT INTO selections (id, dataset_id, version, predicate, row_ids_json, row_count, label, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (selection_id, dataset["id"], version, predicate, json.dumps(row_ids) if row_ids is not None else None,
         count, label if isinstance(label, str) else None, now_iso()),
    )
    return {"selection_id": selection_id, "row_count": count}
