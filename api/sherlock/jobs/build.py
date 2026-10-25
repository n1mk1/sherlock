"""The `build_dashboard` job (TRD §7.3). The dashboard builder is Implementation Plan D4.2; until it
exists the job only marks the dataset `ready` (D3.4), so "Use as is" and the end of cleaning reach
the tabs."""

import asyncio
import sqlite3

from sherlock.jobs.events import EventBus, set_dataset_status
from sherlock.jobs.runner import JobContext, register


def _build(ctx: JobContext) -> dict:
    dataset = ctx.db.execute("SELECT * FROM datasets WHERE id = ?", (ctx.dataset_id,)).fetchone()
    if dataset is None or dataset["deleted_at"]:
        return {"skipped": "dataset deleted"}
    if dataset["status"] != "building":
        ctx.set_dataset_status("building")
    ctx.progress(1, 1, "Building the dashboard")
    ctx.check_cancel()
    ctx.set_dataset_status("ready")
    return {"version": dataset["current_version"], "widgets": 0}


async def run(ctx: JobContext) -> dict:
    return await asyncio.to_thread(_build, ctx)


def on_failure(db: sqlite3.Connection, bus: EventBus | None, job: sqlite3.Row, message: str) -> None:
    """A failed or cancelled build still leaves the data usable: the dataset is ready, with no widgets."""
    dataset = db.execute("SELECT deleted_at FROM datasets WHERE id = ?", (job["dataset_id"],)).fetchone()
    if dataset is not None and not dataset["deleted_at"]:
        set_dataset_status(db, bus, job["dataset_id"], "ready")


register("build_dashboard", run, on_failure)
