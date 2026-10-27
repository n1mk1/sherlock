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

    waiting = db.execute("SELECT id, params_json FROM jobs WHERE dataset_id = ? AND kind = 'stories' AND status = 'queued' "
                         "AND params_json NOT LIKE '%synthesis_ids%' AND params_json NOT LIKE '%answer_ids%'",
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
    if ctx.params.get("answer_ids"):  # an answer card's Refresh: its stored queries run again
        for i, cid in enumerate(ctx.params["answer_ids"], 1):
            ctx.progress(i, len(ctx.params["answer_ids"]), "Running the answer's queries again")
            stories.refresh_answer(env, dataset, cid, ctx.id)
        return {"cards": len(ctx.params["answer_ids"]), "widgets": 0}
    if ctx.params.get("synthesis_ids"):  # a synthesis card's Refresh (TRD §7.4.1)
        from sherlock.stories import synthesis

        columns = list(ws.user_types(env, dataset, dataset["current_version"]))
        for i, cid in enumerate(ctx.params["synthesis_ids"], 1):
            ctx.progress(i, len(ctx.params["synthesis_ids"]), "Writing the synthesis again")
            left: list[str] = []  # sources that aren't usable are left out, and the log says so
            synthesis.refresh(ctx.db, ctx.bus, LLMClient(ctx.settings), scope, dataset, cid, columns, left)
            if left:
                ctx.log(synthesis.left_out_note(left))
        return {"cards": len(ctx.params["synthesis_ids"]), "widgets": 0}
    # Resume (D8.6): a re-queued job skips the widgets whose cards its last run already stored.
    told = set(ctx.state.get("told", []))
    widget_ids = ctx.params.get("widget_ids")
    if told:
        live = [r["id"] for r in ctx.db.execute("SELECT id FROM widgets WHERE dataset_id = ? AND deleted_at IS NULL",
                                                (dataset["id"],))]
        widget_ids = [w for w in (live if widget_ids is None else widget_ids) if w not in told]

    def told_one(widget_id: str) -> None:
        told.add(widget_id)
        ctx.checkpoint({"told": sorted(told)})

    return stories.tell(env, LLMClient(ctx.settings), scope, dataset, widget_ids,
                        reason=ctx.params.get("reason", "build"), progress=ctx.progress, check_cancel=ctx.check_cancel,
                        on_told=told_one)


async def run(ctx: JobContext) -> dict:
    return await asyncio.to_thread(_run, ctx)


def on_failure(db: sqlite3.Connection, bus, job: sqlite3.Row, message: str) -> None:
    """A stories job that failed or was cancelled leaves no card spinning: `updating` becomes `outdated`."""
    if job["dataset_id"]:
        stories.settle_updating(db, bus, job["dataset_id"], job["id"])


register("stories", run, on_failure)
