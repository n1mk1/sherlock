"""The purge job (Schema §6, Implementation Plan D8.6). The runner queues one every `PURGE_INTERVAL_S`
(10 minutes); it belongs to no user's dataset and never shows in anyone's job list.

1. Hard-delete datasets, widgets and cards soft-deleted more than 10 minutes ago (a dataset's files too).
2. Soft-delete datasets past `expires_at`; the next pass hard-deletes them.
3. Delete `job_events` and `widget_cache` rows older than 24 h, and exports (rows and files) older than 24 h.
4. Delete sandbox temp directories older than 1 h.
5. Recompute each dataset's `folder_bytes` and each user's `storage_bytes` (every dataset still on disk,
   soft-deleted ones included).

`llm_calls` and `sandbox_runs` are kept: the daily budgets and the spend report read them.
"""

import asyncio
import shutil
import sqlite3
import time
from datetime import UTC, datetime, timedelta

from sherlock.config import Settings
from sherlock.db.util import now_iso
from sherlock.jobs.runner import JobContext, register
from sherlock.sandbox.runner import sandbox_root
from sherlock.storage import VersionConnections, dataset_dir, folder_bytes, remove_folder

SYSTEM_USER = "system"
GRACE_S = 600
EVENTS_TTL_S = 24 * 3600
EXPORTS_TTL_S = 24 * 3600
SANDBOX_TTL_S = 3600
# Tables keyed by dataset without a cascading foreign key (Schema §2): cleared with the dataset.
LOOSE_TABLES = ("lineage", "user_edited_cells", "issues", "widget_cache", "fact_sheets", "relations", "job_events",
                "thread_summaries", "proposals", "value_index")


def _ago(seconds: float) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def hard_delete_dataset(settings: Settings, db: sqlite3.Connection, cache: VersionConnections | None, row: sqlite3.Row) -> None:
    if cache is not None:
        cache.drop(row["id"])
    remove_folder(dataset_dir(settings, row["user_id"], row["id"]))
    for table in LOOSE_TABLES:
        db.execute(f"DELETE FROM {table} WHERE dataset_id = ?", (row["id"],))  # noqa: S608 - fixed names
    db.execute("DELETE FROM datasets WHERE id = ?", (row["id"],))  # versions, steps, widgets, cards… cascade


def purge(settings: Settings, db: sqlite3.Connection, cache: VersionConnections | None, progress=lambda *_: None) -> dict:
    counts = {"datasets": 0, "expired": 0, "widgets": 0, "cards": 0, "events": 0, "cache": 0, "exports": 0, "sandbox_dirs": 0}
    grace = _ago(GRACE_S)

    progress(1, 5, "Removing deleted CSVs")
    for row in db.execute("SELECT id, user_id FROM datasets WHERE deleted_at IS NOT NULL AND deleted_at < ?", (grace,)).fetchall():
        hard_delete_dataset(settings, db, cache, row)
        counts["datasets"] += 1
    gone = [r["id"] for r in db.execute("SELECT id FROM widgets WHERE deleted_at IS NOT NULL AND deleted_at < ?", (grace,))]
    for wid in gone:  # a widget's card goes with it; its canvas node is pruned on the next read
        db.execute("DELETE FROM cards WHERE widget_id = ?", (wid,))
        db.execute("DELETE FROM fact_sheets WHERE widget_id = ?", (wid,))
        db.execute("UPDATE runs SET widget_id = NULL WHERE widget_id = ?", (wid,))
        db.execute("DELETE FROM widgets WHERE id = ?", (wid,))
    counts["widgets"] = len(gone)
    counts["cards"] = db.execute("DELETE FROM cards WHERE deleted_at IS NOT NULL AND deleted_at < ?", (grace,)).rowcount

    progress(2, 5, "Expiring old CSVs")
    counts["expired"] = db.execute("UPDATE datasets SET deleted_at = ? WHERE deleted_at IS NULL AND expires_at < ?",
                                   (now_iso(), now_iso())).rowcount

    progress(3, 5, "Clearing old events, caches and exports")
    counts["events"] = db.execute("DELETE FROM job_events WHERE created_at < ?", (_ago(EVENTS_TTL_S),)).rowcount
    counts["cache"] = db.execute("DELETE FROM widget_cache WHERE created_at < ?", (_ago(EVENTS_TTL_S),)).rowcount
    for e in db.execute("SELECT e.id, e.path, d.user_id, d.id AS dataset_id FROM exports e JOIN datasets d ON d.id = e.dataset_id "
                        "WHERE e.created_at < ?", (_ago(EXPORTS_TTL_S),)).fetchall():
        if e["path"]:
            (dataset_dir(settings, e["user_id"], e["dataset_id"]) / e["path"]).unlink(missing_ok=True)
        db.execute("DELETE FROM exports WHERE id = ?", (e["id"],))
        counts["exports"] += 1

    progress(4, 5, "Clearing sandbox temp folders")
    root = sandbox_root(settings)
    if root.is_dir():
        cutoff = time.time() - SANDBOX_TTL_S
        for d in root.iterdir():
            try:
                if d.is_dir() and d.stat().st_mtime < cutoff:
                    shutil.rmtree(d, ignore_errors=True)
                    counts["sandbox_dirs"] += 1
            except OSError:
                continue

    progress(5, 5, "Recounting storage")
    for row in db.execute("SELECT id, user_id FROM datasets").fetchall():
        db.execute("UPDATE datasets SET folder_bytes = ? WHERE id = ?",
                   (folder_bytes(dataset_dir(settings, row["user_id"], row["id"])), row["id"]))
    # Soft-deleted datasets still take their space until they're purged.
    db.execute("UPDATE users SET storage_bytes = coalesce((SELECT sum(folder_bytes) FROM datasets d WHERE d.user_id = users.id), 0)")
    return counts


async def run(ctx: JobContext) -> dict:
    return await asyncio.to_thread(purge, ctx.settings, ctx.db, ctx.cache, ctx.progress)


register("purge", run)
