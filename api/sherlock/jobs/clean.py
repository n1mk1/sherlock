"""The `clean` job (TRD §7.2, App Flow §5) and its ending.

A whole-dataset clean sets the dataset to `cleaning` and, when it ends (done, out of budget, or
stopped by the user), queues the dashboard build. If it fails before committing anything, the
dataset goes back to `offer` with the reason in `error`, so the offer screen can show "Build
dashboard without cleaning" and "Try cleaning again" (App Flow §5).
"""

import asyncio
import json
import sqlite3

from sherlock.cleaning.loop import Cleaner
from sherlock.jobs.events import EventBus, set_dataset_status
from sherlock.jobs.runner import JobContext, insert_job, register
from sherlock.llm.client import LLMClient


def is_whole(params: dict) -> bool:
    return (params.get("scope") or {}).get("kind", "all") == "all"


def _clean(ctx: JobContext) -> dict:
    dataset = ctx.db.execute("SELECT * FROM datasets WHERE id = ?", (ctx.dataset_id,)).fetchone()
    if dataset is None or dataset["deleted_at"]:
        return {"skipped": "dataset deleted"}
    if is_whole(ctx.params):
        ctx.set_dataset_status("cleaning")
    result = Cleaner(ctx, LLMClient(ctx.settings)).run()
    if is_whole(ctx.params):
        queue_build(ctx.db, ctx.bus, dataset["user_id"], dataset["id"], ctx.runner)
    return result


def queue_build(db: sqlite3.Connection, bus: EventBus | None, user_id: str, dataset_id: str, runner=None,
                params: dict | None = None) -> sqlite3.Row:
    """Dataset → `building`, then the build_dashboard job (`params` `{automatic: true}` when the
    After upload setting queued it)."""
    set_dataset_status(db, bus, dataset_id, "building")
    job = insert_job(db, user_id, dataset_id, "build_dashboard", params)
    if runner is not None:
        runner.wake()
    return job


async def run(ctx: JobContext) -> dict:
    return await asyncio.to_thread(_clean, ctx)


def on_failure(db: sqlite3.Connection, bus: EventBus | None, job: sqlite3.Row, message: str) -> None:
    dataset = db.execute("SELECT deleted_at, user_id FROM datasets WHERE id = ?", (job["dataset_id"],)).fetchone()
    if dataset is None or dataset["deleted_at"] or not is_whole(json.loads(job["params_json"])):
        return
    if message == "Cancelled.":  # Stop: committed steps stay and the dashboard builds from them
        queue_build(db, bus, dataset["user_id"], job["dataset_id"])
    else:
        set_dataset_status(db, bus, job["dataset_id"], "offer", f"Cleaning stopped: {message}")


register("clean", run, on_failure)
