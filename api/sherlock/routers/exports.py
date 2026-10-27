"""Notebook export (TRD §4.2, §7.7): start or reuse an export, read its status, download it, and the
dialog's preview."""

import json
import sqlite3

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse

from sherlock.db import users
from sherlock.db.connection import get_db
from sherlock.db.users import User
from sherlock.db.util import new_id, now_iso
from sherlock.errors import ApiError, not_found
from sherlock.identity import current_user
from sherlock.notebook.exporter import NotebookOptions, cache_key, export_path, file_name, preview
from sherlock.ownership import Owned, owned, owned_dataset
from sherlock.storage import dataset_dir

router = APIRouter(tags=["exports"])
BLOCKED = {"profiling": "The CSV is still being profiled.", "failed": "This CSV failed to load."}


def _check_status(dataset: sqlite3.Row) -> None:
    if dataset["status"] in BLOCKED:
        raise ApiError(409, "conflict", BLOCKED[dataset["status"]] + " Export notebook is available once it's loaded.")


def remembered(user: User) -> NotebookOptions:
    try:
        stored = user.settings.get("notebook") or {}
        return NotebookOptions.model_validate({k: v for k, v in stored.items() if k in NotebookOptions.model_fields})
    except ValueError:
        return NotebookOptions()


def _out(row: sqlite3.Row, cached: bool = False) -> dict:
    out = {"export_id": row["id"], "job_id": row["job_id"], "cached": cached, "status": row["status"],
           "version": row["version"], "counts": json.loads(row["counts_json"]) if row["counts_json"] else None,
           "error": row["error"]}
    if row["status"] == "done":
        out["download_url"] = f"/api/v1/exports/{row['id']}/download"
    return out


@router.post("/datasets/{dataset_id}/exports/notebook", status_code=201)
def start_export(
    body: NotebookOptions,
    request: Request,
    dataset: sqlite3.Row = Depends(owned_dataset),
    user: User = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    _check_status(dataset)
    stored = users.get(db, user.id)
    users.save_settings(db, user.id, (stored.settings if stored else {}) | {"notebook": body.model_dump(exclude={"up_to_step"})})
    key = cache_key(dataset["current_version"], dataset["state_rev"], body)
    row = db.execute("SELECT * FROM exports WHERE dataset_id = ? AND cache_key = ?", (dataset["id"], key)).fetchone()
    if row is not None:
        path, _ = export_path(request.app.state.settings, dataset, key)
        if row["status"] == "done" and path.is_file():
            return _out(row, cached=True)
        if row["status"] in ("queued", "running"):
            return _out(row)
        db.execute("DELETE FROM exports WHERE id = ?", (row["id"],))  # failed, or its file was purged
    export_id = new_id("exp")
    db.execute(
        "INSERT INTO exports (id, dataset_id, kind, version, options_json, cache_key, status, created_at) "
        "VALUES (?, ?, 'notebook', ?, ?, ?, 'queued', ?)",
        (export_id, dataset["id"], dataset["current_version"], body.model_dump_json(), key, now_iso()),
    )
    job = request.app.state.jobs.enqueue(db, user.id, dataset["id"], "export_notebook", {"export_id": export_id})
    db.execute("UPDATE exports SET job_id = ? WHERE id = ?", (job["id"], export_id))
    return _out(db.execute("SELECT * FROM exports WHERE id = ?", (export_id,)).fetchone())


@router.get("/datasets/{dataset_id}/exports/notebook/preview")
def export_preview(
    include_data: bool | None = Query(default=None),
    include_runs: bool | None = Query(default=None),
    up_to_step: int | None = Query(default=None, ge=1),
    dataset: sqlite3.Row = Depends(owned_dataset),
    user: User = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """The dialog's sentence and notes; options not given come from the user's remembered ones,
    which the answer repeats as `options`."""
    _check_status(dataset)
    given = {k: v for k, v in {"include_data": include_data, "include_runs": include_runs,
                               "up_to_step": up_to_step}.items() if v is not None}
    options = NotebookOptions.model_validate(remembered(user).model_dump() | given)
    try:
        out = preview(db, dataset, options)
    except ValueError as exc:
        raise ApiError(422, "invalid", str(exc)) from None
    return {**out, "options": options.model_dump()}


def _export_row(db: sqlite3.Connection, export_id: str) -> sqlite3.Row:
    row = db.execute("SELECT * FROM exports WHERE id = ?", (export_id,)).fetchone()
    if row is None:
        raise not_found("Export not found")
    return row


@router.get("/exports/{export_id}")
def get_export(export_id: str, _: Owned = Depends(owned("export")), db: sqlite3.Connection = Depends(get_db)) -> dict:
    return _out(_export_row(db, export_id))


@router.get("/exports/{export_id}/download")
def download_export(
    export_id: str, request: Request, _: Owned = Depends(owned("export")), db: sqlite3.Connection = Depends(get_db)
) -> FileResponse:
    row = _export_row(db, export_id)
    dataset = db.execute("SELECT * FROM datasets WHERE id = ?", (row["dataset_id"],)).fetchone()
    if row["status"] != "done" or not row["path"]:
        raise ApiError(409, "conflict", "This notebook isn't ready yet.")
    path = dataset_dir(request.app.state.settings, dataset["user_id"], dataset["id"]) / row["path"]
    if not path.is_file():
        raise not_found("This export has expired. Export the notebook again.")
    return FileResponse(path, media_type="application/x-ipynb+json", filename=file_name(dataset, row["version"]))
