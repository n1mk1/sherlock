"""The `review_issues` job (TRD §3.3, §7.2; PRD CLEAN-8c): rate a version's findings in the background.
Queued by the profile job after each upload, and by `POST …/clean/plan` when the version has no
review yet and none is waiting (`review.queue`). When it ends, an open draft plan on that version
takes the levels and reasons (items the user ticked, unticked or reworded keep their choice) and
`plan.updated` goes out; a plan already started isn't changed."""

import asyncio
import json

from sherlock.cleaning import plan as plans
from sherlock.cleaning import review
from sherlock.jobs.events import emit
from sherlock.jobs.runner import JobContext, register
from sherlock.llm.client import CallScope
from sherlock.profile import service as profile_service


def _run(ctx: JobContext) -> dict:
    dataset = ctx.db.execute("SELECT * FROM datasets WHERE id = ?", (ctx.dataset_id,)).fetchone()
    if dataset is None or dataset["deleted_at"]:
        return {"skipped": "dataset deleted"}
    version = ctx.params["version"]
    if review.stored(ctx.db, dataset["id"], version) is not None:
        return {"skipped": "already reviewed"}
    card = profile_service.get_or_build(ctx.settings, ctx.db, ctx.cache, dataset, version)
    scope = CallScope(user_id=dataset["user_id"], dataset_id=dataset["id"], job_id=ctx.id,
                      on_wait=lambda text: ctx.log(text, icon="wait"))
    outcome = review.review(ctx.settings, ctx.db, dataset, card, scope, progress=ctx.progress)
    pid = plans.draft_id(ctx.db, dataset["id"])
    row = plans.get(ctx.db, pid) if pid else None
    if row is not None and row["version"] == version:
        items = plans.reviewed(json.loads(row["items_json"]), review.stored(ctx.db, dataset["id"], version) or {})
        plans.save(ctx.db, row["id"], items)
        emit(ctx.db, ctx.bus, dataset["id"], dataset["user_id"], "plan.updated", {"plan_id": row["id"]}, ctx.id)
    return {"review": outcome, "version": version}


async def run(ctx: JobContext) -> dict:
    return await asyncio.to_thread(_run, ctx)


register("review_issues", run)
