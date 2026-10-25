"""The `stories` job (TRD §7.4 step 6): fact sheets and cards for some or all widgets, then the
overview. Queued when the dashboard is built, when a widget is added or changed, and by a card's
Refresh; the cascade runs the same pipeline itself (§7.6)."""

import asyncio
import sqlite3

from sherlock.jobs.runner import JobContext, insert_job, register
from sherlock.llm.client import CallScope, LLMClient
from sherlock.stories import service as stories
from sherlock.widgets import service as ws


def queue_stories(db: sqlite3.Connection, dataset: sqlite3.Row, widget_ids: list[str] | None, reason: str) -> None:
    """One waiting stories job per dataset absorbs the next request (the union of their widgets)."""
    import json

    waiting = db.execute("SELECT id, params_json FROM jobs WHERE dataset_id = ? AND kind = 'stories' AND status = 'queued'",
                         (dataset["id"],)).fetchone()
    if waiting:
        params = json.loads(waiting["params_json"])
        if params.get("widget_ids") is not None:
            merged = None if widget_ids is None else sorted(set(params["widget_ids"]) | set(widget_ids))
            db.execute("UPDATE jobs SET params_json = ? WHERE id = ?",
                       (json.dumps({**params, "widget_ids": merged}), waiting["id"]))
        return
    insert_job(db, dataset["user_id"], dataset["id"], "stories", {"widget_ids": widget_ids, "reason": reason})


def _run(ctx: JobContext) -> dict:
    dataset = ctx.db.execute("SELECT * FROM datasets WHERE id = ?", (ctx.dataset_id,)).fetchone()
    if dataset is None or dataset["deleted_at"]:
        return {"skipped": "dataset deleted"}
    env = ws.Env(ctx.settings, ctx.db, ctx.cache, ctx.bus)
    scope = CallScope(user_id=dataset["user_id"], dataset_id=dataset["id"], job_id=ctx.id,
                      on_wait=lambda text: ctx.log(text, icon="wait"))
    return stories.tell(env, LLMClient(ctx.settings), scope, dataset, ctx.params.get("widget_ids"),
                        reason=ctx.params.get("reason", "build"), progress=ctx.progress, check_cancel=ctx.check_cancel)


async def run(ctx: JobContext) -> dict:
    return await asyncio.to_thread(_run, ctx)


register("stories", run)
