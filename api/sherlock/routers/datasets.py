"""Datasets (TRD §4.2): upload, sample, list, get. An import queues the profile job."""

import json
import sqlite3
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile, status
from pydantic import BaseModel, ValidationError

from sherlock.db import datasets as datasets_repo
from sherlock.db.connection import get_db
from sherlock.db.users import User
from sherlock.errors import ApiError
from sherlock.identity import current_user
from sherlock.ingest.importer import import_csv
from sherlock.ingest.options import ImportOptions
from sherlock.ownership import owned_dataset
from sherlock.profile import service as profile_service

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
    status: Literal["profiling", "offer", "cleaning", "building", "ready", "failed"]
    current_version: int
    row_count: int | None
    column_count: int | None
    created_at: str
    last_opened_at: str | None
    last_tab: Literal["csv", "dashboard", "flow"] | None
    cleaning_progress: CleaningProgress | None = None
    error: str | None = None
    # For the library row ("offer · 4 issues") and the version pill ("v7 · 6 steps"): the issues on the
    # current version's DataCard (null until it's built) and the steps in its effective chain.
    issue_count: int | None = None
    step_count: int = 0


def to_dataset(row: sqlite3.Row, db: sqlite3.Connection | None = None) -> Dataset:
    issue_count, step_count = _counts(db, row) if db is not None else (None, 0)
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
    """The bundled Titanic file; returns the user's existing sample instead of a duplicate."""
    existing = datasets_repo.find_sample(db, user.id)
    if existing is not None:
        return to_dataset(existing, db)
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
