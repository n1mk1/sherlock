"""The `cascade` job (TRD §7.6, App Flow §16): after a new version, bring the dashboard and its
stories up to date, touching only what depends on what changed.

- **What changed.** The steps since the oldest widget's `version_built`: their target columns and
  added or removed columns (an undo adds the steps it replayed). Rows added, deleted, quarantined
  or restored, or a change of columns, affect every widget.
- **Widgets.** An affected widget (one whose scope or query names a changed column) re-runs its
  query on the new version, records `version_built` and emits `widget.updated`. The others only
  record the new version.
- **Runs.** A finished run of an earlier version whose target, features or row predicate meet the
  changed columns is marked outdated (PRD ML-9). Its widgets show "Outdated" with Re-run under
  "Story updates: Ask first", and re-run on the new version otherwise.
- **Cards.** The affected widgets' cards are narrated again (cut 6: no material-change check), an
  edited card gets a suggestion, and with "Story updates: Ask first" they're marked outdated
  instead; then the overview.
- **Debounce.** A commit queues one cascade per dataset: one already queued, or running but still in
  its 2 s wait, absorbs the next, so saves within 2 s cascade once.
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


def changes(db: sqlite3.Connection, dataset_id: str, since: int, version: int) -> tuple[set[str], bool]:
    """(changed columns, every widget affected) for the steps after `since` up to `version`."""
    cols: set[str] = set()
    everything = False
    steps = db.execute("SELECT * FROM steps WHERE dataset_id = ? AND to_version > ? AND to_version <= ?",
                       (dataset_id, since, version)).fetchall()
    for s in steps:
        ids = [s["id"]] + (json.loads(s["replayed_step_ids_json"]) if s["replayed_step_ids_json"] else [])
        for sid in ids:
            r = db.execute("SELECT * FROM steps WHERE id = ?", (sid,)).fetchone()
            cols.update(json.loads(r["column_targets_json"]))
            if json.loads(r["columns_added_json"]) or json.loads(r["columns_removed_json"]):
                everything = True
            if r["kind"] == "clean" and r["created_by"] == "system":
                everything = True  # typing (or undoing it) changes column types
            impact = json.loads(r["impact_json"])
            if impact.get("rows_added") or impact.get("rows_deleted") or impact.get("quarantined"):
                everything = True
            if r["edits_json"] and json.loads(r["edits_json"]).get("restore_row_ids"):
                everything = True
        if s["kind"] == "undo" and s["undone_step_id"]:
            u = db.execute("SELECT * FROM steps WHERE id = ?", (s["undone_step_id"],)).fetchone()
            cols.update(json.loads(u["column_targets_json"]))
            impact = json.loads(u["impact_json"])
            if impact.get("rows_added") or impact.get("rows_deleted") or impact.get("quarantined") \
                    or json.loads(u["columns_added_json"]) or json.loads(u["columns_removed_json"]) \
                    or (u["kind"] == "clean" and u["created_by"] == "system"):
                everything = True
    return cols, everything


def _cascade(ctx: JobContext) -> dict:
    from sherlock.llm.client import CallScope, LLMClient
    from sherlock.routers.me import effective_settings
    from sherlock.db import users
    from sherlock.ml import runner as ml
    from sherlock.stories import facts as fx
    from sherlock.stories import service as stories
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
    stale = [r for r in rows if r["version_built"] < version]
    since = min((r["version_built"] for r in stale), default=version)
    changed, everything = changes(ctx.db, dataset["id"], since, version)
    env = widgets.Env(ctx.settings, ctx.db, ctx.cache, ctx.bus)
    memo: dict[int, tuple[set[str], bool]] = {}

    def since_version(v: int) -> tuple[set[str], bool]:
        if v not in memo:
            memo[v] = changes(ctx.db, dataset["id"], v, version)
        return memo[v]

    outdated_runs = set(ml.outdate(ctx.db, ctx.bus, dataset, since_version, ctx.id))
    user = users.get(ctx.db, dataset["user_id"])
    ask = effective_settings(user.settings if user else {}).story_updates == "ask"
    affected = []
    for r in stale:
        spec = json.loads(r["spec_json"])
        if spec["op"]["type"] == "ml":
            if r["run_id"] in outdated_runs:
                affected.append(r)
            continue
        try:
            deps = set(fx.depends_on(spec, widgets.compiled(env, dataset, spec, version, []))) if spec["op"]["type"] == "sql" else set()
        except ApiError:
            deps, everything_for_it = set(), True
        else:
            everything_for_it = False
        if everything or everything_for_it or deps & changed:
            affected.append(r)
    cards = [c["id"] for c in ctx.db.execute(
        f"SELECT id FROM cards WHERE dataset_id = ? AND deleted_at IS NULL AND widget_id IN ({','.join('?' * len(affected))})",
        (dataset["id"], *[r["id"] for r in affected])).fetchall()] if affected else []
    ctx.emit("cascade.started", {"version": version, "widget_ids": [r["id"] for r in affected], "card_ids": cards,
                                 "run_ids": sorted(outdated_runs), "columns": sorted(changed), "all": everything})
    errors = 0
    for i, row in enumerate(stale, 1):
        ctx.check_cancel()
        ctx.progress(i, len(stale) + 1, f"Updating {len(affected)} widget{'s' if len(affected) != 1 else ''}")
        if json.loads(row["spec_json"])["op"]["type"] == "ml":
            if row in affected and not ask:
                try:
                    ml.rerun_widget(env, dataset, row)  # "Story updates: Automatic" re-runs it on the new version
                except ApiError as exc:
                    ctx.db.execute("UPDATE widgets SET status = 'error', error = ? WHERE id = ?", (exc.message, row["id"]))
                    errors += 1
                ctx.emit("widget.updated", widgets.to_widget(widgets.get_row(ctx.db, row["id"])))
            elif row not in affected:
                ctx.db.execute("UPDATE widgets SET version_built = ? WHERE id = ?", (version, row["id"]))
            continue  # an outdated one keeps its run's version and shows "Outdated" with Re-run
        status, error = "ready", None
        if row in affected and json.loads(row["spec_json"])["op"]["type"] == "sql":
            try:
                widgets.data(env, dataset, row, [], version)
            except ApiError as exc:
                status, error, errors = "error", exc.message, errors + 1
        ctx.db.execute("UPDATE widgets SET status = ?, error = ?, version_built = ?, updated_at = ? WHERE id = ?",
                       (status, error, version, now_iso(), row["id"]))
        if row in affected:
            ctx.emit("widget.updated", widgets.to_widget(widgets.get_row(ctx.db, row["id"])))
    told = {"cards": 0}
    with_cards = [r["id"] for r in affected
                  if ctx.db.execute("SELECT 1 FROM cards WHERE widget_id = ? AND deleted_at IS NULL", (r["id"],)).fetchone()]
    if with_cards:
        ctx.progress(len(stale) + 1, len(stale) + 1, f"Updating {len(with_cards)} {'story' if len(with_cards) == 1 else 'stories'}")
        scope = CallScope(user_id=dataset["user_id"], dataset_id=dataset["id"], job_id=ctx.id,
                          on_wait=lambda text: ctx.log(text, icon="wait"))
        told = stories.tell(env, LLMClient(ctx.settings), scope, dataset, with_cards, reason="cascade", ask_first=ask,
                            check_cancel=ctx.check_cancel)
    counts = {"widgets": len(affected), "errors": errors, "cards": told.get("cards", 0),
              "outdated": told.get("outdated", 0), "runs": len(outdated_runs)}
    ctx.emit("cascade.done", {"version": version, "counts": counts})
    return {"version": version, **counts}


async def run(ctx: JobContext) -> dict:
    return await asyncio.to_thread(_cascade, ctx)


register("cascade", run)
