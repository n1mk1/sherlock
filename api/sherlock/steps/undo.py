"""Undo (TRD §7.8). Undoing the last step in the current version's effective chain E makes a
new version that points at the latest version whose chain is E without that step: no data is
rewritten, nothing is deleted, and the undo is itself a step.

Undo of an earlier step needs replay of the steps after it (Implementation Plan D5.5); until
then it answers `confirm_required` with the steps to replay, and `409` once confirmed.
"""

import json

from sherlock.db.util import new_id, now_iso
from sherlock.errors import not_found
from sherlock.profile import service as profile_service
from sherlock.steps.commit import Context, conflict, current_version_row, emit_version_created, load_step
from sherlock.steps.notebook import UNDO_CODE
from sherlock.storage import dataset_dir, dataset_lock


def is_typing_step(step) -> bool:
    return step["kind"] == "clean" and step["created_by"] == "system"


def undo_step(ctx: Context, dataset_id: str, step_id: str, base_version: int, confirm: bool) -> dict:
    db = ctx.db
    dataset = db.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
    target = db.execute("SELECT * FROM steps WHERE id = ? AND dataset_id = ?", (step_id, dataset_id)).fetchone()
    if target is None:
        raise not_found("Step not found")
    folder = dataset_dir(ctx.settings, dataset["user_id"], dataset_id)
    with dataset_lock(folder):
        dataset = db.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
        if dataset["current_version"] != base_version:
            raise conflict(
                f"The data changed since you started (now version {dataset['current_version']}). Reload and try again.",
                current_version=dataset["current_version"],
            )
        current = current_version_row(db, dataset_id)
        chain = json.loads(current["effective_step_ids_json"])
        if target["kind"] == "undo" or step_id not in chain:
            raise conflict("This step isn't part of the current data, so there's nothing to undo.")

        later = chain[chain.index(step_id) + 1:]
        replay = [db.execute("SELECT no FROM steps WHERE id = ?", (s,)).fetchone()[0] for s in later]
        warning = "typing" if is_typing_step(target) else None
        if not confirm and (replay or warning):
            return {"confirm_required": True, "replay_needed": replay, "warning": warning}
        if replay:
            raise conflict(
                "Undoing a step that later steps build on needs those steps replayed, which isn't available yet. "
                "Undo the later steps first.",
                replay_needed=replay,
            )

        remaining = chain[:-1]
        source = None
        for row in db.execute(
            "SELECT * FROM versions WHERE dataset_id = ? ORDER BY version DESC", (dataset_id,)
        ).fetchall():
            if json.loads(row["effective_step_ids_json"]) == remaining:
                source = row
                break
        if source is None:
            raise conflict("No earlier version matches; rebuilding from the raw file needs replay, which isn't available yet.")

        new_version = current["version"] + 1
        undo_id = new_id("stp")
        number = db.execute("SELECT coalesce(max(no), 0) + 1 FROM steps WHERE dataset_id = ?", (dataset_id,)).fetchone()[0]
        reverted = db.execute(
            "SELECT count(*) FROM lineage WHERE step_id = ? AND version = ? AND column != '_row'",
            (step_id, target["to_version"]),
        ).fetchone()[0]
        impact = {
            "rows_in": current["row_count"], "rows_out": source["row_count"], "cells_changed": reverted,
            "quarantined": 0, "parse_failures": 0, "rows_added": 0, "rows_deleted": 0, "before_after": [],
        }
        now = now_iso()
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute(
                "INSERT INTO steps (id, dataset_id, no, kind, from_version, to_version, summary, column_targets_json, "
                "columns_added_json, columns_removed_json, notebook_code, impact_json, undone_step_id, created_by, created_at) "
                "VALUES (?, ?, ?, 'undo', ?, ?, ?, ?, '[]', '[]', ?, ?, ?, 'user', ?)",
                (undo_id, dataset_id, number, current["version"], new_version,
                 f"Undid step {target['no']}: {target['summary']}", target["column_targets_json"],
                 UNDO_CODE.format(no=target["no"]), json.dumps(impact), step_id, now),
            )
            db.execute(
                "INSERT INTO versions (dataset_id, version, parquet_path, row_count, column_count, columns_json, "
                "step_id, effective_step_ids_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (dataset_id, new_version, source["parquet_path"], source["row_count"], source["column_count"],
                 source["columns_json"], undo_id, json.dumps(remaining), now),
            )
            db.execute("DELETE FROM user_edited_cells WHERE dataset_id = ? AND step_id = ?", (dataset_id, step_id))
            db.execute(
                "UPDATE datasets SET current_version = ?, row_count = ?, column_count = ?, state_rev = state_rev + 1 "
                "WHERE id = ?",
                (new_version, source["row_count"], source["column_count"], dataset_id),
            )
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            raise
    dataset = db.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
    profile_service.get_or_build(ctx.settings, db, ctx.cache, dataset, new_version)
    step = load_step(db, undo_id)
    emit_version_created(ctx, dataset, step, new_version)
    return {"step": step, "version": new_version}
