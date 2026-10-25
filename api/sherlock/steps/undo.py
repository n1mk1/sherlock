"""Undo (TRD §7.8). Undo removes one step from the current version's effective chain E and makes
the new current version from what's left; nothing is deleted, and the undo is itself a step.

- The new chain is E without the step. If a version with exactly that chain exists (always, for the
  latest step), the new version points at its Parquet and no data is rewritten.
- Otherwise the new version starts from the latest version whose chain is the longest prefix of the
  new chain (v1, whose chain is empty, at worst) and replays the rest (`steps/replay.py`, D5.5).
  Undo of a step that later steps follow asks first (`confirm_required` with the step numbers to
  replay); a replay that fails is `409` with `failed_step_id` and `reason`, and changes nothing.
"""

import json
import sqlite3

from sherlock.db.util import new_id, now_iso
from sherlock.errors import not_found
from sherlock.profile import service as profile_service
from sherlock.steps.commit import Context, conflict, current_version_row, emit_version_created, load_step
from sherlock.steps.diff import diff_versions
from sherlock.steps.notebook import UNDO_CODE
from sherlock.steps.replay import ReplayError, replay
from sherlock.storage import dataset_dir, dataset_lock, folder_bytes


def is_typing_step(step) -> bool:
    return step["kind"] == "clean" and step["created_by"] == "system"


def _base(db: sqlite3.Connection, dataset_id: str, chain: list[str]) -> tuple[sqlite3.Row, int]:
    """The latest version whose effective chain is the longest prefix of `chain`, and that length."""
    best, best_len = None, -1
    for row in db.execute("SELECT * FROM versions WHERE dataset_id = ? ORDER BY version DESC", (dataset_id,)):
        have = json.loads(row["effective_step_ids_json"])
        if len(have) > best_len and chain[: len(have)] == have:
            best, best_len = row, len(have)
            if best_len == len(chain):
                break
    return best, best_len


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
        replay_nos = [db.execute("SELECT no FROM steps WHERE id = ?", (s,)).fetchone()[0] for s in later]
        warning = "typing" if is_typing_step(target) else None
        if not confirm and (replay_nos or warning):
            return {"confirm_required": True, "replay_needed": replay_nos, "warning": warning}

        remaining = [s for s in chain if s != step_id]
        source, have = _base(db, dataset_id, remaining)
        to_replay = [db.execute("SELECT * FROM steps WHERE id = ?", (s,)).fetchone() for s in remaining[have:]]
        new_version = current["version"] + 1
        replayed = []
        if to_replay:
            relative = f"versions/v{new_version}.parquet"
            try:
                replayed = replay(ctx, dataset, folder, folder / source["parquet_path"], to_replay, folder / relative)
            except ReplayError as exc:
                raise conflict(
                    f"Step {exc.step_no} couldn't be replayed: {exc.reason}. Nothing was undone.",
                    failed_step_id=exc.step_id, reason=exc.reason,
                ) from exc
            parquet, row_count, columns_json = relative, *_shape(folder / relative)
        else:
            parquet, row_count, columns_json = source["parquet_path"], source["row_count"], source["columns_json"]
        column_count = len([c for c in json.loads(columns_json) if c["name"] not in ("_row_id", "_quarantine_reason")])

        undo_id = new_id("stp")
        number = db.execute("SELECT coalesce(max(no), 0) + 1 FROM steps WHERE dataset_id = ?", (dataset_id,)).fetchone()[0]
        diff = diff_versions(folder / current["parquet_path"], folder / parquet)
        impact = {
            "rows_in": current["row_count"], "rows_out": row_count, "cells_changed": diff.cells_changed,
            "quarantined": 0, "parse_failures": 0, "rows_added": len(diff.added_row_ids),
            "rows_deleted": len(diff.deleted_row_ids), "before_after": diff.before_after,
        }
        summary = f"Undid step {target['no']}: {target['summary']}"
        if replay_nos:
            summary += f" (replayed {_nos(replay_nos)})"
        now = now_iso()
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute(
                "INSERT INTO steps (id, dataset_id, no, kind, from_version, to_version, summary, column_targets_json, "
                "columns_added_json, columns_removed_json, notebook_code, impact_json, undone_step_id, "
                "replayed_step_ids_json, created_by, created_at) "
                "VALUES (?, ?, ?, 'undo', ?, ?, ?, ?, '[]', '[]', ?, ?, ?, ?, 'user', ?)",
                (undo_id, dataset_id, number, current["version"], new_version, summary, target["column_targets_json"],
                 UNDO_CODE.format(no=target["no"]), json.dumps(impact), step_id,
                 json.dumps([r.step_id for r in replayed]) if replayed else None, now),
            )
            db.execute(
                "INSERT INTO versions (dataset_id, version, parquet_path, row_count, column_count, columns_json, "
                "step_id, effective_step_ids_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (dataset_id, new_version, parquet, row_count, column_count, columns_json, undo_id,
                 json.dumps(remaining), now),
            )
            dropped = db.execute("SELECT row_id, column FROM user_edited_cells WHERE dataset_id = ? AND step_id = ?",
                                 (dataset_id, step_id)).fetchall()
            db.execute("DELETE FROM user_edited_cells WHERE dataset_id = ? AND step_id = ?", (dataset_id, step_id))
            for r in replayed:
                db.executemany(
                    "INSERT INTO lineage (dataset_id, step_id, row_id, column, old_value, new_value, flag, version) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [(dataset_id, r.step_id, x[0], x[1], x[2], x[3], x[4], new_version) for x in r.lineage],
                )
                db.executemany(
                    "INSERT OR REPLACE INTO user_edited_cells (dataset_id, row_id, column, step_id) VALUES (?, ?, ?, ?)",
                    [(dataset_id, rid, col, r.step_id) for rid, col in r.edited_cells],
                )
            _reprotect(db, dataset_id, dropped, remaining)
            size = folder_bytes(folder)
            db.execute(
                "UPDATE datasets SET current_version = ?, row_count = ?, column_count = ?, state_rev = state_rev + 1, "
                "folder_bytes = ? WHERE id = ?",
                (new_version, row_count, column_count, size, dataset_id),
            )
            db.execute("UPDATE users SET storage_bytes = storage_bytes + ? WHERE id = ?",
                       (size - dataset["folder_bytes"], dataset["user_id"]))
            db.execute("COMMIT")
        except Exception:
            db.execute("ROLLBACK")
            if to_replay:
                (folder / parquet).unlink(missing_ok=True)
            raise
    dataset = db.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
    profile_service.get_or_build(ctx.settings, db, ctx.cache, dataset, new_version)
    step = load_step(db, undo_id)
    emit_version_created(ctx, dataset, step, new_version)
    return {"step": step, "version": new_version}


def _reprotect(db: sqlite3.Connection, dataset_id: str, cells: list, chain: list[str]) -> None:
    """A cell the undone step had edited stays protected if an edit batch still in the chain edited it
    too: its row points at the latest such batch (Schema §2.7)."""
    if not cells or not chain:
        return
    marks = ", ".join("?" * len(chain))
    edits = [r[0] for r in db.execute(
        f"SELECT id FROM steps WHERE dataset_id = ? AND kind = 'edit' AND id IN ({marks})", (dataset_id, *chain))]
    if not edits:
        return
    marks = ", ".join("?" * len(edits))
    for row_id, column in cells:
        latest = db.execute(
            f"SELECT step_id FROM lineage WHERE dataset_id = ? AND row_id = ? AND column = ? AND step_id IN ({marks}) "
            "ORDER BY version DESC LIMIT 1", (dataset_id, row_id, column, *edits)).fetchone()
        if latest:
            db.execute("INSERT OR IGNORE INTO user_edited_cells (dataset_id, row_id, column, step_id) VALUES (?, ?, ?, ?)",
                       (dataset_id, row_id, column, latest[0]))


def _shape(path) -> tuple[int, str]:
    import duckdb

    from sherlock.storage import sql_path

    conn = duckdb.connect(":memory:")
    try:
        rows = conn.execute(f"SELECT count(*) FROM read_parquet({sql_path(path)})").fetchone()[0]
        cols = [{"name": r[0], "type": r[1]} for r in conn.execute(f"DESCRIBE SELECT * FROM read_parquet({sql_path(path)})").fetchall()]
        return rows, json.dumps(cols)
    finally:
        conn.close()


def _nos(nos: list[int]) -> str:
    if len(nos) == 1:
        return f"step {nos[0]}"
    if nos == list(range(nos[0], nos[-1] + 1)):
        return f"steps {nos[0]}–{nos[-1]}"
    return "steps " + ", ".join(str(n) for n in nos)
