"""The `profile` job (TRD §7.1 steps 3–6), queued by every upload and sample import.

First the typing step (3b) commits step 1 on version 1, which also profiles version 2. Then the
job builds or reads the current version's DataCard (issues and value index included) and sets the
dataset's status, which follows the user's "After upload" setting (step 6, App Flow §4): `ask`
ends in `offer`; `always` queues a whole-dataset clean (status `cleaning`); `never` queues the
dashboard build (status `building`).
"""

import asyncio
import sqlite3

from sherlock.db import users
from sherlock.jobs.events import EventBus, set_dataset_status
from sherlock.jobs.runner import JobContext, insert_job, register
from sherlock.profile import service as profile_service
from sherlock.profile import typing as typing_step
from sherlock.steps.commit import Context


def _profile(ctx: JobContext) -> dict:
    dataset = ctx.db.execute("SELECT * FROM datasets WHERE id = ?", (ctx.dataset_id,)).fetchone()
    if dataset is None or dataset["deleted_at"]:
        return {"skipped": "dataset deleted"}
    if dataset["status"] != "profiling":  # a retry after a failure
        ctx.set_dataset_status("profiling")
    ctx.progress(1, 2, f"Typing {dataset['column_count']} columns")
    step = typing_step.apply(Context(ctx.settings, ctx.db, ctx.cache, ctx.bus), dataset, ctx.id)
    if step is not None:
        ctx.log(step["summary"], icon="check", step_id=step["id"])
    ctx.check_cancel()
    ctx.progress(2, 2, f"Profiling {dataset['column_count']} columns")
    dataset = ctx.db.execute("SELECT * FROM datasets WHERE id = ?", (ctx.dataset_id,)).fetchone()
    card = profile_service.get_or_build(ctx.settings, ctx.db, ctx.cache, dataset)
    ctx.check_cancel()
    _after_upload(ctx, dataset)
    return {"version": card["version"], "issues": len(card["issues"]), "typing_step_id": step["id"] if step else None}


def _after_upload(ctx: JobContext, dataset: sqlite3.Row) -> None:
    from sherlock.jobs.clean import queue_build
    from sherlock.routers.me import effective_settings

    user = users.get(ctx.db, dataset["user_id"])
    choice = effective_settings(user.settings if user else {}).after_upload
    if choice == "always":
        ctx.set_dataset_status("cleaning")
        insert_job(ctx.db, dataset["user_id"], dataset["id"], "clean",
                   {"mode": "auto", "scope": {"kind": "all", "selection_id": None, "row_ids": None},
                    "include_user_edited": False, "automatic": True})
        ctx.runner.wake()
    elif choice == "never":
        queue_build(ctx.db, ctx.bus, dataset["user_id"], dataset["id"], ctx.runner)
    else:
        ctx.set_dataset_status("offer")


async def run(ctx: JobContext) -> dict:
    return await asyncio.to_thread(_profile, ctx)


def on_failure(db: sqlite3.Connection, bus: EventBus | None, job: sqlite3.Row, message: str) -> None:
    """The dataset stays in the library marked failed (App Flow §3.3)."""
    dataset = db.execute("SELECT deleted_at FROM datasets WHERE id = ?", (job["dataset_id"],)).fetchone()
    if dataset is not None and not dataset["deleted_at"]:
        set_dataset_status(db, bus, job["dataset_id"], "failed", message)


register("profile", run, on_failure)
