"""The `profile` job (TRD §7.1 steps 3–6), queued by every upload and sample import.

First the typing step (3b) commits step 1 on version 1, which also profiles version 2. Then the
job builds or reads the current version's DataCard (issues and value index included) and sets the
dataset's status, which follows the user's "After upload" setting (step 6, App Flow §4): `ask`
ends in `offer`; `always` ("Open the cleaning plan") makes a draft cleaning plan and ends in
`offer`, so the plan screen opens by itself and nothing is cleaned without a click; `never` ("I'll
clean it myself") queues the dashboard build (status `building`) with `automatic: true`.
"""

import asyncio
import sqlite3

from sherlock.cleaning import plan as plans
from sherlock.db import users
from sherlock.jobs.events import EventBus, emit, set_dataset_status
from sherlock.jobs.runner import JobContext, register
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
    _after_upload(ctx, dataset, card)
    return {"version": card["version"], "issues": len(card["issues"]), "typing_step_id": step["id"] if step else None}


def _after_upload(ctx: JobContext, dataset: sqlite3.Row, card: dict) -> None:
    from sherlock.jobs.clean import queue_build
    from sherlock.routers.me import effective_settings

    user = users.get(ctx.db, dataset["user_id"])
    choice = effective_settings(user.settings if user else {}).after_upload
    if choice == "never":
        queue_build(ctx.db, ctx.bus, dataset["user_id"], dataset["id"], ctx.runner, {"automatic": True})
        return
    if choice == "always" and plans.draft_id(ctx.db, dataset["id"]) is None:
        row = plans.create(ctx.db, dataset, card, source="after_upload")
        emit(ctx.db, ctx.bus, dataset["id"], dataset["user_id"], "plan.updated", {"plan_id": row["id"]}, ctx.id)
    ctx.set_dataset_status("offer")


async def run(ctx: JobContext) -> dict:
    return await asyncio.to_thread(_profile, ctx)


def on_failure(db: sqlite3.Connection, bus: EventBus | None, job: sqlite3.Row, message: str) -> None:
    """The dataset stays in the library marked failed (App Flow §3.3)."""
    dataset = db.execute("SELECT deleted_at FROM datasets WHERE id = ?", (job["dataset_id"],)).fetchone()
    if dataset is not None and not dataset["deleted_at"]:
        set_dataset_status(db, bus, job["dataset_id"], "failed", message)


register("profile", run, on_failure)
