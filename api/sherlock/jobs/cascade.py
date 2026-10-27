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
- **Audit.** Last, `stories.trust.audit` marks any `ready` card whose numbers may not hold on the
  version `outdated`; the result's `audited` counts them, and 0 means the cascade did its job.
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
# Impact fields that mean a step changed which rows there are, so every widget is affected.
ROWS_CHANGED = ("rows_added", "rows_deleted", "quarantined", "rows_restored")


def queue_cascade(db: sqlite3.Connection, dataset: sqlite3.Row, reason: str = "version") -> None:
    """Queue a cascade for the dataset unless one is already waiting. Only datasets with something
    that can go stale need one: a widget, a card or a run (an answer card or a run can
    exist without a dashboard)."""
    has_any = db.execute(
        "SELECT 1 WHERE EXISTS (SELECT 1 FROM widgets WHERE dataset_id = ? AND deleted_at IS NULL) "
        "OR EXISTS (SELECT 1 FROM cards WHERE dataset_id = ? AND deleted_at IS NULL) "
        "OR EXISTS (SELECT 1 FROM runs WHERE dataset_id = ?)", (dataset["id"], dataset["id"], dataset["id"])).fetchone()
    if not has_any:
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
            if any(impact.get(k) for k in ROWS_CHANGED):
                everything = True
            if r["edits_json"] and json.loads(r["edits_json"]).get("restore_row_ids"):
                everything = True
        if s["kind"] == "undo" and s["undone_step_id"]:
            u = db.execute("SELECT * FROM steps WHERE id = ?", (s["undone_step_id"],)).fetchone()
            cols.update(json.loads(u["column_targets_json"]))
            impact = json.loads(u["impact_json"])
            # Undoing a restore quarantines those rows again, like undoing any change of rows.
            restored = bool(u["edits_json"] and json.loads(u["edits_json"]).get("restore_row_ids"))
            if any(impact.get(k) for k in ROWS_CHANGED) or restored \
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
    # A run already outdated (under Ask first) is still out of date: its widgets stay affected, so they
    # re-run once the user switches to Automatic.
    stale_runs = outdated_runs | {r["id"] for r in ctx.db.execute(
        "SELECT id FROM runs WHERE dataset_id = ? AND status = 'outdated'", (dataset["id"],))}
    columns = list(widgets.user_types(env, dataset, version))
    user = users.get(ctx.db, dataset["user_id"])
    ask = effective_settings(user.settings if user else {}).story_updates == "ask"
    affected = []
    for r in stale:
        spec = json.loads(r["spec_json"])
        if spec["op"]["type"] == "ml":
            if r["run_id"] in stale_runs:
                affected.append(r)
            continue
        try:
            deps = set(fx.depends_on(spec, widgets.compiled(env, dataset, spec, version, []), columns=columns)) \
                if spec["op"]["type"] == "sql" else set()
        except ApiError:
            deps, everything_for_it = set(), True
        else:
            everything_for_it = False
        if everything or everything_for_it or deps & changed:
            affected.append(r)
    cards = [c["id"] for c in ctx.db.execute(
        f"SELECT id FROM cards WHERE dataset_id = ? AND deleted_at IS NULL AND widget_id IN ({','.join('?' * len(affected))})",
        (dataset["id"], *[r["id"] for r in affected])).fetchall()] if affected else []
    # An export cached from before the cascade, or made during it, isn't reused after.
    ctx.db.execute("UPDATE datasets SET state_rev = state_rev + 1 WHERE id = ?", (dataset["id"],))
    ctx.emit("cascade.started", {"version": version, "widget_ids": [r["id"] for r in affected], "card_ids": cards,
                                 "run_ids": sorted(outdated_runs), "columns": sorted(changed), "all": everything})
    errors = 0
    # Widget id → the `updated_at` its `version_built` write is guarded by. The versions move only after the
    # cards are told, so a cascade that dies or is overtaken mid-tell leaves them stale and the next one
    # tells them again; a widget the user changed meanwhile (a new `updated_at`) is left to that change.
    built: dict[str, str] = {}
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
                built[row["id"]] = row["updated_at"]
            continue  # an outdated one keeps its run's version and shows "Outdated" with Re-run
        if row not in affected:
            built[row["id"]] = row["updated_at"]  # its query reads nothing that changed: status and error stay
            continue
        status, error = "ready", None
        if json.loads(row["spec_json"])["op"]["type"] == "sql":
            try:
                widgets.data(env, dataset, row, [], version)
            except ApiError as exc:
                status, error, errors = "error", exc.message, errors + 1
        now = now_iso()
        written = ctx.db.execute("UPDATE widgets SET status = ?, error = ?, updated_at = ? WHERE id = ? AND updated_at = ?",
                                 (status, error, now, row["id"], row["updated_at"])).rowcount
        if written:
            built[row["id"]] = now
        ctx.emit("widget.updated", widgets.to_widget(widgets.get_row(ctx.db, row["id"])))
    told = {"cards": 0}
    with_cards = [r["id"] for r in affected
                  if ctx.db.execute("SELECT 1 FROM cards WHERE widget_id = ? AND deleted_at IS NULL", (r["id"],)).fetchone()]
    if ctx.params.get("reason") == "settings" and not ask:  # switched to Automatic: tell the cards left outdated
        with_cards += [r["id"] for r in rows if r["id"] not in with_cards and ctx.db.execute(
            "SELECT 1 FROM cards WHERE widget_id = ? AND deleted_at IS NULL AND status = 'outdated'", (r["id"],)).fetchone()]
    if with_cards:
        ctx.progress(len(stale) + 1, len(stale) + 1, f"Updating {len(with_cards)} {'story' if len(with_cards) == 1 else 'stories'}")
        scope = CallScope(user_id=dataset["user_id"], dataset_id=dataset["id"], job_id=ctx.id,
                          on_wait=lambda text: ctx.log(text, icon="wait"))
        told = stories.tell(env, LLMClient(ctx.settings), scope, dataset, with_cards, reason="cascade", ask_first=ask,
                            check_cancel=ctx.check_cancel)
    overtaken = set(told.get("overtaken", []))  # a newer version came in mid-tell: its cascade tells them
    for wid, stamp in built.items():
        if wid not in overtaken:  # only forward: an older cascade never moves a widget back
            ctx.db.execute("UPDATE widgets SET version_built = MAX(version_built, ?) WHERE id = ? AND updated_at = ?",
                           (version, wid, stamp))
    # Answer cards re-run their stored queries, or go outdated under Ask first.
    answers = stories.recheck_answers(env, dataset, since_version, ask_first=ask, job_id=ctx.id)
    # Under Automatic a synthesis whose cited numbers moved is written again, by a stories job
    # that runs once this cascade ends; one with fewer than two usable sources keeps its Refresh.
    rewrite = [] if ask else _syntheses_to_rewrite(ctx.db, dataset)
    if rewrite:
        insert_job(ctx.db, dataset["user_id"], dataset["id"], "stories", {"synthesis_ids": rewrite, "reason": "cascade"})
        ctx.runner.wake()
    counts = {"widgets": len(affected), "errors": errors, "cards": told.get("cards", 0),
              "outdated": told.get("outdated", 0), "runs": len(outdated_runs)}
    # The invariant: no `ready` card shows numbers that may not hold on this version. 0 when the
    # cascade did its job; a newer version's cascade, queued behind this one, checks its own version.
    from sherlock.stories import trust

    fresh = ctx.db.execute("SELECT * FROM datasets WHERE id = ?", (dataset["id"],)).fetchone()
    audited = trust.audit(ctx.db, ctx.bus, fresh, ctx.id) if fresh["current_version"] == version else 0
    ctx.db.execute("UPDATE datasets SET state_rev = state_rev + 1 WHERE id = ?", (dataset["id"],))
    ctx.emit("cascade.done", {"version": version, "counts": counts})
    return {"version": version, **counts, "answers": answers, "audited": audited}


def _syntheses_to_rewrite(db: sqlite3.Connection, dataset: sqlite3.Row) -> list[str]:
    """Synthesis cards showing `sources_changed` whose sources still give at least two usable cards."""
    from sherlock.stories import synthesis

    out = []
    for r in db.execute("SELECT id, source_card_ids_json FROM cards WHERE dataset_id = ? AND kind = 'synthesis' "
                        "AND deleted_at IS NULL AND status = 'sources_changed'", (dataset["id"],)).fetchall():
        if len(synthesis.sources(db, dataset["id"], json.loads(r["source_card_ids_json"] or "[]"))) >= 2:
            out.append(r["id"])
    return out


async def run(ctx: JobContext) -> dict:
    return await asyncio.to_thread(_cascade, ctx)


def on_failure(db: sqlite3.Connection, bus, job: sqlite3.Row, message: str) -> None:
    """A cascade that failed or was cancelled leaves no card spinning: those still `updating` become
    `outdated` (Refresh). Its widgets' versions didn't move, so the next cascade tells them again."""
    from sherlock.stories import service as stories

    if job["dataset_id"]:
        stories.settle_updating(db, bus, job["dataset_id"], job["id"])


register("cascade", run, on_failure)
