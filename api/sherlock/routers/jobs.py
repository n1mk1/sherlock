"""Jobs (TRD §4.10): list, get, cancel, retry, log."""

import json
import sqlite3

from fastapi import APIRouter, Depends, Query, Request, Response, status

from sherlock.db.connection import get_db
from sherlock.db.users import User
from sherlock.errors import ApiError
from sherlock.identity import current_user
from sherlock.jobs.runner import FINISHED, cancel_job, get_job, to_job
from sherlock.ownership import Owned, check_dataset, owned

router = APIRouter(tags=["jobs"])
LIST_LIMIT = 200


@router.get("/jobs")
def list_jobs(
    dataset_id: str | None = Query(default=None),
    user: User = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> list[dict]:
    """Newest first: one dataset's jobs, or all of the user's (jobs of deleted datasets left out)."""
    if dataset_id is not None:
        check_dataset(db, user.id, dataset_id)
        rows = db.execute(
            "SELECT * FROM jobs WHERE dataset_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (dataset_id, LIST_LIMIT),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT j.* FROM jobs j LEFT JOIN datasets d ON d.id = j.dataset_id "
            "WHERE j.user_id = ? AND (j.dataset_id IS NULL OR d.deleted_at IS NULL) "
            "ORDER BY j.created_at DESC, j.id DESC LIMIT ?",
            (user.id, LIST_LIMIT),
        ).fetchall()
    return [to_job(r) for r in rows]


@router.get("/jobs/{jid}")
def get(job: Owned = Depends(owned("job")), db: sqlite3.Connection = Depends(get_db)) -> dict:
    return to_job(get_job(db, job.id))


@router.post("/jobs/{jid}/cancel", status_code=status.HTTP_204_NO_CONTENT)
def cancel(request: Request, job: Owned = Depends(owned("job")), db: sqlite3.Connection = Depends(get_db)) -> Response:
    """Idempotent: cancelling a finished job does nothing."""
    cancel_job(db, request.app.state.bus, job.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/jobs/{jid}/retry", status_code=status.HTTP_201_CREATED)
def retry(request: Request, job: Owned = Depends(owned("job")), db: sqlite3.Connection = Depends(get_db)) -> dict:
    """A new job with the same kind, dataset and params. Only a failed or cancelled job can be retried."""
    row = get_job(db, job.id)
    if row["status"] not in FINISHED or row["status"] == "done":
        raise ApiError(409, "conflict", f"Only a failed or cancelled job can be retried; this one is {row['status']}.")
    new = request.app.state.jobs.enqueue(db, row["user_id"], row["dataset_id"], row["kind"], json.loads(row["params_json"]))
    return to_job(new)


@router.get("/jobs/{jid}/log")
def job_log(job: Owned = Depends(owned("job")), db: sqlite3.Connection = Depends(get_db)) -> dict:
    """The job's `job.log` lines, oldest first (kept 24 h)."""
    rows = db.execute(
        "SELECT data_json FROM job_events WHERE job_id = ? AND type = 'job.log' ORDER BY id", (job.id,)
    ).fetchall()
    return {"entries": [json.loads(r[0]) for r in rows]}
