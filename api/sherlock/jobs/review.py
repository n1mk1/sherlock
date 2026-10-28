"""The `review_issues` job (TRD §3.3, §7.2; PRD CLEAN-8c): rate a version's findings in the background.
Queued by the profile job after each upload, and by `POST …/clean/plan` when the version has no
review yet and none is waiting (`review.queue`). When it ends, an open draft plan on that version
takes the levels and reasons (items the user ticked, unticked or reworded keep their choice) and
`plan.updated` goes out; a plan already started isn't changed.

Grounding runs first (`cleaning/ground.py`, docs/plans/tavily.md §3.2): Tavily looks up what the columns mean
(`notes.updated` goes out when notes were stored), and the excerpts it read go to the suggested checks."""

import asyncio
import json
import logging

from sherlock.cleaning import plan as plans
from sherlock.cleaning import review
from sherlock.cleaning.ground import ground
from sherlock.cleaning.rules import service as rule_service
from sherlock.jobs.events import emit
from sherlock.jobs.runner import JobContext, register
from sherlock.llm.client import CallScope
from sherlock.profile import service as profile_service

log = logging.getLogger("sherlock.review")


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
    frame = rule_service.frame_for(ctx.settings, ctx.cache, ctx.db, dataset, version)
    # Grounding first (docs/plans/tavily.md §3.2): column notes and the excerpts the suggested checks are written from.
    try:
        excerpts = ground(ctx.settings, ctx.db, dataset, card, scope, bus=ctx.bus)
    except Exception:  # noqa: BLE001 - grounding is extra: whatever goes wrong, the review goes on
        log.exception("grounding failed")
        excerpts = []
    suggested = review.suggest(ctx.settings, ctx.db, dataset, card, frame, scope, excerpts=excerpts)  # so they're rated too
    outcome = review.review(ctx.settings, ctx.db, dataset, card, scope, progress=ctx.progress, extra=suggested)
    pid = plans.draft_id(ctx.db, dataset["id"])
    row = plans.get(ctx.db, pid) if pid else None
    if row is not None and row["version"] == version:
        items = plans.reviewed(json.loads(row["items_json"]), review.stored(ctx.db, dataset["id"], version) or {})
        plans.save(ctx.db, row["id"], items)
        emit(ctx.db, ctx.bus, dataset["id"], dataset["user_id"], "plan.updated", {"plan_id": row["id"]}, ctx.id)
    return {"review": outcome, "version": version, "suggested": len(suggested), "excerpts": len(excerpts)}


async def run(ctx: JobContext) -> dict:
    return await asyncio.to_thread(_run, ctx)


register("review_issues", run)
