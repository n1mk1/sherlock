"""The `build_dashboard` job (TRD §7.3): runs the dashboard builder, then marks the dataset `ready`.
It is queued after cleaning and by "Use as is"."""

import asyncio
import sqlite3

from sherlock.dashboard.builder import build
from sherlock.jobs.events import EventBus, set_dataset_status
from sherlock.jobs.runner import JobContext, register


async def run(ctx: JobContext) -> dict:
    return await asyncio.to_thread(build, ctx)


def on_failure(db: sqlite3.Connection, bus: EventBus | None, job: sqlite3.Row, message: str) -> None:
    """A failed or cancelled build still leaves the data usable: the dataset is ready with whatever
    widgets were made."""
    dataset = db.execute("SELECT deleted_at FROM datasets WHERE id = ?", (job["dataset_id"],)).fetchone()
    if dataset is not None and not dataset["deleted_at"]:
        set_dataset_status(db, bus, job["dataset_id"], "ready")


register("build_dashboard", run, on_failure)
