"""Steps (TRD §4.4): list, get, undo."""

import json
import sqlite3

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from sherlock.db.connection import get_db
from sherlock.errors import not_found
from sherlock.ownership import owned_dataset
from sherlock.steps.commit import Context, current_version_row, load_step
from sherlock.steps.undo import undo_step

router = APIRouter(tags=["steps"])


class UndoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: bool = False
    base_version: int = Field(ge=1)


def _active(db: sqlite3.Connection, dataset_id: str) -> set[str]:
    return set(json.loads(current_version_row(db, dataset_id)["effective_step_ids_json"]))


@router.get("/datasets/{dataset_id}/steps")
def list_steps(row: sqlite3.Row = Depends(owned_dataset), db: sqlite3.Connection = Depends(get_db)) -> list[dict]:
    """Newest first. `active` is whether the step's effect is in the current version (undone steps
    and undo steps are not)."""
    active = _active(db, row["id"])
    ids = [r[0] for r in db.execute("SELECT id FROM steps WHERE dataset_id = ? ORDER BY no DESC", (row["id"],))]
    return [{**load_step(db, i), "active": i in active} for i in ids]


@router.get("/datasets/{dataset_id}/steps/{step_id}")
def get_step(step_id: str, row: sqlite3.Row = Depends(owned_dataset), db: sqlite3.Connection = Depends(get_db)) -> dict:
    found = db.execute("SELECT 1 FROM steps WHERE id = ? AND dataset_id = ?", (step_id, row["id"])).fetchone()
    if found is None:
        raise not_found("Step not found")
    return {**load_step(db, step_id), "active": step_id in _active(db, row["id"])}


@router.post("/datasets/{dataset_id}/steps/{step_id}/undo")
def undo(
    step_id: str,
    body: UndoRequest,
    request: Request,
    row: sqlite3.Row = Depends(owned_dataset),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    ctx = Context(request.app.state.settings, db, request.app.state.duckdb)
    return undo_step(ctx, row["id"], step_id, body.base_version, body.confirm)
