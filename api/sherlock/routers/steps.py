"""Steps (TRD §4.4): list, get, undo; the toolbar's Undo and Redo, up to `undo_depth` states back."""

import json
import sqlite3

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from sherlock.db.connection import get_db
from sherlock.errors import not_found
from sherlock.ownership import owned_dataset
from sherlock.steps.commit import Context, current_version_row, load_step
from sherlock.steps.undo import history, quick_undo, redo_step, undo_step

router = APIRouter(tags=["steps"])


class UndoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: bool = False
    base_version: int = Field(ge=1)


class MoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    ctx = Context(request.app.state.settings, db, request.app.state.duckdb, request.app.state.bus)
    return undo_step(ctx, row["id"], step_id, body.base_version, body.confirm)


@router.get("/datasets/{dataset_id}/history")
def get_history(request: Request, row: sqlite3.Row = Depends(owned_dataset), db: sqlite3.Connection = Depends(get_db)) -> dict:
    """`{ version, undo: { step_id, no, summary } | null, redo: … | null, depth_left }` for the toolbar."""
    return history(db, row["id"], request.app.state.settings.undo_depth)


@router.post("/datasets/{dataset_id}/undo")
def undo_latest(body: MoveRequest, request: Request, row: sqlite3.Row = Depends(owned_dataset),
                db: sqlite3.Connection = Depends(get_db)) -> dict:
    """The toolbar's Undo: `{ step, version }`; `409` when there's nothing left to undo in a row."""
    ctx = Context(request.app.state.settings, db, request.app.state.duckdb, request.app.state.bus)
    return quick_undo(ctx, row["id"], body.base_version)


@router.post("/datasets/{dataset_id}/redo")
def redo(body: MoveRequest, request: Request, row: sqlite3.Row = Depends(owned_dataset),
         db: sqlite3.Connection = Depends(get_db)) -> dict:
    """The toolbar's Redo: `{ step, version }`; `409` when there's nothing to redo."""
    ctx = Context(request.app.state.settings, db, request.app.state.duckdb, request.app.state.bus)
    return redo_step(ctx, row["id"], body.base_version)
