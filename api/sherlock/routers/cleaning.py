"""Cleaning (TRD §4.4): start a clean, use the data as is, read the report."""

import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from sherlock.cleaning.report import build_report
from sherlock.db.connection import get_db
from sherlock.errors import ApiError
from sherlock.jobs.clean import queue_build
from sherlock.jobs.runner import to_job
from sherlock.ownership import owned_dataset
from sherlock.ratelimit import llm_rate_limit

router = APIRouter(tags=["cleaning"])
STARTABLE = ("offer", "ready")


class CleanScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["all", "selection", "new_rows"] = "all"
    selection_id: str | None = None
    row_ids: list[int] | None = None


class CleanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["auto", "stepwise"] = "auto"
    scope: CleanScope = Field(default_factory=CleanScope)
    include_user_edited: bool = False


def _busy(db: sqlite3.Connection, dataset_id: str) -> bool:
    return db.execute(
        "SELECT 1 FROM jobs WHERE dataset_id = ? AND kind IN ('profile', 'clean', 'build_dashboard') "
        "AND status IN ('queued', 'running') LIMIT 1", (dataset_id,),
    ).fetchone() is not None


@router.post("/datasets/{dataset_id}/clean", status_code=status.HTTP_201_CREATED, dependencies=[Depends(llm_rate_limit)])
def start_clean(
    body: CleanRequest,
    request: Request,
    dataset: sqlite3.Row = Depends(owned_dataset),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Queue a clean job on the current version. Step-by-step mode is P1 (PRD CLEAN-10)."""
    if body.mode == "stepwise":
        raise ApiError(422, "invalid", "Step-by-step cleaning isn't available yet. Use auto.")
    if body.scope.kind == "selection" and not body.scope.selection_id:
        raise ApiError(422, "invalid", "scope: a selection scope needs selection_id")
    if dataset["status"] not in STARTABLE:
        raise ApiError(409, "conflict", f"This CSV is {dataset['status']}; cleaning can start once that finishes.")
    if _busy(db, dataset["id"]):
        raise ApiError(409, "conflict", "A job is already running on this CSV.")
    job = request.app.state.jobs.enqueue(db, dataset["user_id"], dataset["id"], "clean", body.model_dump())
    return to_job(job)


@router.post("/datasets/{dataset_id}/use-as-is", status_code=status.HTTP_201_CREATED)
def use_as_is(
    request: Request,
    dataset: sqlite3.Row = Depends(owned_dataset),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Skip cleaning: build the dashboard on the current (typed) version."""
    if dataset["status"] != "offer":
        raise ApiError(409, "conflict", f"This CSV is {dataset['status']}, not waiting for a choice.")
    if _busy(db, dataset["id"]):
        raise ApiError(409, "conflict", "A job is already running on this CSV.")
    job = queue_build(db, request.app.state.bus, dataset["user_id"], dataset["id"], request.app.state.jobs)
    return to_job(job)


@router.get("/datasets/{dataset_id}/report")
def report(
    job_id: str | None = Query(default=None),
    dataset: sqlite3.Row = Depends(owned_dataset),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    return build_report(db, dataset["id"], job_id)
