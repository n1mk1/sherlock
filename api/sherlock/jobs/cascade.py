"""The `cascade` job (TRD §7.6, App Flow §16): after a new version, bring the dashboard up to date.

Cascade v0 (Implementation Plan D5.5): every live widget re-runs its query on the new version
(warming the data cache), records `version_built`, and emits `widget.updated`; `cascade.started`
and `cascade.done` frame the run. A commit queues one cascade per dataset: one already queued
absorbs the next, and a job waits until 2 s after it was queued, so saves within 2 s cascade once.
"""

import asyncio
import json
import sqlite3
import time
from datetime import UTC, datetime

from sherlock.db.util import now_iso
from sherlock.errors import ApiError
from sherlock.jobs.runner import JobContext, insert_job, register

DEBOUNCE_S = 2.0


def queue_cascade(db: sqlite3.Connection, dataset: sqlite3.Row, reason: str = "version") -> None:
    """Queue a cascade for the dataset unless one is already waiting. Only datasets with a
    dashboard need one."""
    has_widgets = db.execute("SELECT 1 FROM widgets WHERE dataset_id = ? AND deleted_at IS NULL LIMIT 1",
                             (dataset["id"],)).fetchone()
    if not has_widgets:
        return
    for job in db.execute("SELECT status, created_at FROM jobs WHERE dataset_id = ? AND kind = 'cascade' "
                          "AND status IN ('queued', 'running')", (dataset["id"],)):
        if job["status"] == "queued" or _age_s(job["created_at"]) < DEBOUNCE_S - 0.2:
            return  # that one hasn't read the version yet, so it will cascade this one too
    insert_job(db, dataset["user_id"], dataset["id"], "cascade", {"reason": reason})


def _age_s(created_at: str) -> float:
    created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    return (datetime.now(UTC) - created).total_seconds()


def _cascade(ctx: JobContext) -> dict:
    from sherlock.widgets import service as widgets

    wait = DEBOUNCE_S - _age_s(ctx.row["created_at"])
    if wait > 0:
        time.sleep(wait)
    dataset = ctx.db.execute("SELECT * FROM datasets WHERE id = ?", (ctx.dataset_id,)).fetchone()
    if dataset is None or dataset["deleted_at"]:
        return {"skipped": "dataset deleted"}
    version = dataset["current_version"]
    rows = ctx.db.execute("SELECT * FROM widgets WHERE dataset_id = ? AND deleted_at IS NULL ORDER BY order_no",
                          (dataset["id"],)).fetchall()
    ids = [r["id"] for r in rows]
    ctx.emit("cascade.started", {"version": version, "widget_ids": ids, "card_ids": [], "run_ids": []})
    env = widgets.Env(ctx.settings, ctx.db, ctx.cache, ctx.bus)
    errors = 0
    for i, row in enumerate(rows, 1):
        ctx.check_cancel()
        ctx.progress(i, len(rows), f"Updating {len(rows)} widget{'s' if len(rows) != 1 else ''}")
        status, error = "ready", None
        if json.loads(row["spec_json"])["op"]["type"] == "sql":
            try:
                widgets.data(env, dataset, row, [], version)
            except ApiError as exc:
                status, error, errors = "error", exc.message, errors + 1
        ctx.db.execute("UPDATE widgets SET status = ?, error = ?, version_built = ?, updated_at = ? WHERE id = ?",
                       (status, error, version, now_iso(), row["id"]))
        ctx.emit("widget.updated", widgets.to_widget(widgets.get_row(ctx.db, row["id"])))
    counts = {"widgets": len(rows), "errors": errors, "cards": 0, "runs": 0}
    ctx.emit("cascade.done", {"version": version, "counts": counts})
    return {"version": version, **counts}


async def run(ctx: JobContext) -> dict:
    return await asyncio.to_thread(_cascade, ctx)


register("cascade", run)
