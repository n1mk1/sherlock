"""The `profile` job (TRD §7.1 steps 3–6), queued by every upload and sample import.

First the typing step (3b) commits step 1 on version 1, which also profiles version 2. Then the
job builds or reads the current version's DataCard (issues and value index included) and sets the
dataset's status. Step 6
says the status follows the "After upload" setting; until the Cleaner (D3) and the dashboard
builder (D4) exist, every setting ends in `offer`.
"""

import asyncio
import sqlite3

from sherlock.jobs.events import EventBus, set_dataset_status
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
    ctx.set_dataset_status("offer")
    return {"version": card["version"], "issues": len(card["issues"]), "typing_step_id": step["id"] if step else None}


async def run(ctx: JobContext) -> dict:
    return await asyncio.to_thread(_profile, ctx)


def on_failure(db: sqlite3.Connection, bus: EventBus | None, job: sqlite3.Row, message: str) -> None:
    """The dataset stays in the library marked failed (App Flow §3.3)."""
    dataset = db.execute("SELECT deleted_at FROM datasets WHERE id = ?", (job["dataset_id"],)).fetchone()
    if dataset is not None and not dataset["deleted_at"]:
        set_dataset_status(db, bus, job["dataset_id"], "failed", message)


register("profile", run, on_failure)
