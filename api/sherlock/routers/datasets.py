"""Datasets (TRD §4.2): upload, sample, list, get. An import queues the profile job."""

import json
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from sherlock.db import datasets as datasets_repo
from sherlock.db.connection import get_db
from sherlock.db.users import User
from sherlock.db.util import now_iso
from sherlock.errors import ApiError
from sherlock.identity import current_user
from sherlock.ingest.importer import import_csv
from sherlock.ingest.options import ImportOptions
from sherlock import sample_seed
from sherlock.cleaning import plan as plans
from sherlock.jobs.clean import mark_ready
from sherlock.jobs.events import emit
from sherlock.jobs.runner import cancel_job
from sherlock.ownership import check_dataset, owned_dataset
from sherlock.profile import service as profile_service
from sherlock.ratelimit import llm_rate_limit
from sherlock.storage import dataset_dir, raw_path

router = APIRouter(tags=["datasets"])

SAMPLE_CSV = Path(__file__).resolve().parents[2] / "samples" / "titanic3.csv"
SAMPLE_NAME = "titanic3.csv (sample)"


class CleaningProgress(BaseModel):
    step: int
    of: int
    pct: float


class Dataset(BaseModel):
    id: str
    name: str
    status: Literal["profiling", "offer", "cleaning", "ready", "failed"]
    current_version: int
    row_count: int | None
    column_count: int | None
    created_at: str
    last_opened_at: str | None
    last_tab: Literal["csv"] | None
    cleaning_progress: CleaningProgress | None = None
    error: str | None = None
    # For the library row ("offer · 4 issues") and the version pill ("v7 · 6 steps"): the issues on the
    # current version's DataCard (null until it's built) and the steps in its effective chain.
    issue_count: int | None = None
    step_count: int = 0
    # The draft cleaning plan, while there is one (PRD CLEAN-8a): the offer screen shows the plan instead.
    clean_plan_id: str | None = None


def to_dataset(row: sqlite3.Row, db: sqlite3.Connection | None = None) -> Dataset:
    issue_count, step_count = _counts(db, row) if db is not None else (None, 0)
    plan_id = plans.draft_id(db, row["id"]) if db is not None else None
    return Dataset(
        id=row["id"],
        name=row["name"],
        status=row["status"],
        current_version=row["current_version"],
        row_count=row["row_count"],
        column_count=row["column_count"],
        created_at=row["created_at"],
        last_opened_at=row["last_opened_at"],
        last_tab=row["last_tab"],
        error=row["error"],
        issue_count=issue_count,
        step_count=step_count,
        clean_plan_id=plan_id,
    )


def _counts(db: sqlite3.Connection, row: sqlite3.Row) -> tuple[int | None, int]:
    version = row["current_version"]
    chain = db.execute(
        "SELECT effective_step_ids_json FROM versions WHERE dataset_id = ? AND version = ?", (row["id"], version)
    ).fetchone()
    steps = len(json.loads(chain[0])) if chain else 0
    built = db.execute(
        "SELECT 1 FROM datacards WHERE dataset_id = ? AND version = ?", (row["id"], version)
    ).fetchone()
    if built is None:
        return None, steps
    issues = db.execute(
        "SELECT count(*) FROM issues WHERE dataset_id = ? AND version = ?", (row["id"], version)
    ).fetchone()[0]
    return issues, steps


def _parse_options(raw: str | None) -> ImportOptions:
    if not raw:
        return ImportOptions()
    try:
        return ImportOptions.model_validate(json.loads(raw))
    except (json.JSONDecodeError, ValidationError) as exc:
        message = exc.errors()[0]["msg"] if isinstance(exc, ValidationError) else "not valid JSON"
        raise ApiError(422, "invalid", f"options: {message}") from None


@router.get("/datasets", response_model=list[Dataset])
def list_datasets(user: User = Depends(current_user), db: sqlite3.Connection = Depends(get_db)):
    return [to_dataset(row, db) for row in datasets_repo.list_for_user(db, user.id)]


@router.post("/datasets", response_model=Dataset, status_code=status.HTTP_201_CREATED)
def upload_dataset(
    request: Request,
    file: UploadFile = File(...),
    options: str | None = Form(None),
    user: User = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    settings = request.app.state.settings
    limit = settings.max_upload_mb
    if file.size is not None and file.size > limit * 1024 * 1024:
        size_mb = file.size / (1024 * 1024)
        shown = f"{size_mb:.1f}" if size_mb < 10 else f"{size_mb:.0f}"
        raise ApiError(413, "too_large", f"This file is {shown} MB. The limit is {limit} MB.")
    row = import_csv(settings, db, user.id, file.file, file.filename or "upload.csv", _parse_options(options))
    request.app.state.jobs.enqueue(db, user.id, row["id"], "profile")
    return to_dataset(row, db)


@router.post("/datasets/sample", response_model=Dataset)
def sample_dataset(
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
):
    """The bundled Titanic file; returns the user's existing sample instead of a duplicate. With the
    cached seed (D9.1) it's a clone, ready at once, with its cleaning and analysis; without it, the file is imported and goes through the pipeline live."""
    existing = datasets_repo.find_sample(db, user.id)
    if existing is not None:
        return to_dataset(existing, db)
    seed = sample_seed.seed_dir(request.app.state.settings)
    if seed is not None:
        row = sample_seed.clone(request.app.state.settings, db, user.id, seed, SAMPLE_NAME)
        emit(db, request.app.state.bus, row["id"], user.id, "dataset.status",
             {"status": row["status"], "current_version": row["current_version"]})
        response.status_code = status.HTTP_201_CREATED
        return to_dataset(row, db)
    with SAMPLE_CSV.open("rb") as fh:
        row = import_csv(
            request.app.state.settings, db, user.id, fh, SAMPLE_CSV.name, ImportOptions(),
            name=SAMPLE_NAME, is_sample=True,
        )
    request.app.state.jobs.enqueue(db, user.id, row["id"], "profile")
    response.status_code = status.HTTP_201_CREATED
    return to_dataset(row, db)


@router.get("/datasets/{dataset_id}/datacard")
def get_datacard(
    request: Request,
    version: int | None = Query(default=None, ge=1),
    row: sqlite3.Row = Depends(owned_dataset),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """The version's DataCard (TRD §6.1), built on first request and cached per version."""
    return profile_service.get_or_build(request.app.state.settings, db, request.app.state.duckdb, row, version)


@router.get("/datasets/{dataset_id}", response_model=Dataset)
def get_dataset(row: sqlite3.Row = Depends(owned_dataset), db: sqlite3.Connection = Depends(get_db)):
    """Opening a dataset records `last_opened_at`, which orders the library."""
    datasets_repo.mark_opened(db, row["id"])
    return to_dataset(datasets_repo.get(db, row["user_id"], row["id"]), db)


class DatasetPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=200)
    last_tab: Literal["csv"] | None = None


@router.patch("/datasets/{dataset_id}", response_model=Dataset)
def patch_dataset(body: DatasetPatch, row: sqlite3.Row = Depends(owned_dataset), db: sqlite3.Connection = Depends(get_db)):
    """Rename (LOAD-5) and remember the last tab (App Flow §1)."""
    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise ApiError(422, "invalid", "name: can't be empty")
        db.execute("UPDATE datasets SET name = ? WHERE id = ?", (name, row["id"]))
    if body.last_tab is not None:
        db.execute("UPDATE datasets SET last_tab = ? WHERE id = ?", (body.last_tab, row["id"]))
    return to_dataset(datasets_repo.get(db, row["user_id"], row["id"]), db)


@router.delete("/datasets/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(request: Request, row: sqlite3.Row = Depends(owned_dataset), db: sqlite3.Connection = Depends(get_db)):
    """Soft delete: the dataset and everything under it disappear at once and can be restored for
    10 minutes; the purge job (Implementation Plan D8.6) removes the files after that. Its jobs are
    cancelled."""
    db.execute("UPDATE datasets SET deleted_at = ? WHERE id = ?", (now_iso(), row["id"]))
    for job in db.execute("SELECT id FROM jobs WHERE dataset_id = ? AND status IN ('queued', 'running')", (row["id"],)):
        cancel_job(db, request.app.state.bus, job["id"])
    request.app.state.duckdb.drop(row["id"])
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/datasets/{dataset_id}/restore", response_model=Dataset)
def restore_dataset(
    request: Request, dataset_id: str, user: User = Depends(current_user), db: sqlite3.Connection = Depends(get_db),
):
    """Undo a delete within 10 minutes. Work that was cancelled by the delete starts again."""
    row = check_dataset(db, user.id, dataset_id, include_deleted=True)
    if row["deleted_at"]:
        if row["deleted_at"] < _minutes_ago(RESTORE_MINUTES):
            raise ApiError(404, "not_found", "Dataset not found")
        db.execute("UPDATE datasets SET deleted_at = NULL WHERE id = ?", (row["id"],))
        busy = db.execute("SELECT 1 FROM jobs WHERE dataset_id = ? AND status IN ('queued', 'running')", (row["id"],)).fetchone()
        if not busy and row["status"] == "profiling":
            request.app.state.jobs.enqueue(db, user.id, row["id"], "profile")
        elif not busy and row["status"] == "cleaning":
            mark_ready(db, request.app.state.bus, row["id"])
    return to_dataset(datasets_repo.get(db, user.id, row["id"]), db)


@router.get("/datasets/{dataset_id}/raw.csv")
def raw_csv(request: Request, row: sqlite3.Row = Depends(owned_dataset)) -> FileResponse:
    """The original upload, byte for byte (TRD §4.2)."""
    path = raw_path(dataset_dir(request.app.state.settings, row["user_id"], row["id"]))
    stem = re.sub(r"\.(csv|tsv|txt)$", "", row["name"].replace(" (sample)", ""), flags=re.I)
    filename = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{stem}-raw.csv")
    return FileResponse(path, media_type="text/csv", filename=filename)


RESTORE_MINUTES = 10


def _minutes_ago(minutes: int) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# --- Column notes and the data dictionary (PRD LOAD-7, TRD §4.2, §7.1) ------------------------------


class ColumnNote(BaseModel):
    column: str
    kind: Literal["dictionary", "found", "web"]  # found: a dictionary Sherlock looked up itself
    description: str             # Sherlock's sentence from the source, with no digits
    excerpt: str | None          # the source's own words, as the page has them
    source_url: str
    source_title: str | None
    retrieved_at: str            # the day Tavily returned the page


class ColumnNotes(BaseModel):
    notes: list[ColumnNote]
    note: str | None = None      # the one line shown when the dictionary couldn't be read (fail-soft)


class DictionaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=2000)


@router.get("/datasets/{dataset_id}/column-notes", response_model=ColumnNotes)
def get_column_notes(row: sqlite3.Row = Depends(owned_dataset), db: sqlite3.Connection = Depends(get_db)):
    """What the dataset's columns mean, from a data dictionary the user linked or from the web: the CSV
    tab's header tooltip reads it. Metadata, not data: no version."""
    from sherlock.agent.web import notes_for

    return {"notes": notes_for(db, row["id"])}


@router.post("/datasets/{dataset_id}/dictionary", response_model=ColumnNotes, dependencies=[Depends(llm_rate_limit)])
def read_dictionary(
    body: DictionaryRequest,
    request: Request,
    row: sqlite3.Row = Depends(owned_dataset),
    db: sqlite3.Connection = Depends(get_db),
):
    """Read the data dictionary at the URL the user typed (the import preview's "Data dictionary URL"):
    Tavily extract, map when the page is a site root, then Super matches excerpts to columns. It fails
    soft: no key, a timeout or an unreadable page answer `200` with no notes and a one-line `note`."""
    import time

    from sherlock.agent.web import DICTIONARY_WALL_S
    from sherlock.agent.web import read_dictionary as read
    from sherlock.llm.client import CallScope, LLMClient
    from sherlock.web.client import WebClient
    from sherlock.query import context as qx

    settings = request.app.state.settings
    env = qx.Env(settings, db, request.app.state.duckdb, request.app.state.bus)
    columns = list(qx.user_types(env, row, row["current_version"]))
    scope = CallScope(user_id=row["user_id"], dataset_id=row["id"], deadline=time.monotonic() + DICTIONARY_WALL_S)
    return read(LLMClient(settings), scope, WebClient(settings), db, row["id"], body.url.strip(), columns)
