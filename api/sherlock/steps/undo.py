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
from sherlock.steps.notebook import REDO_CODE, UNDO_CODE
from sherlock.steps.replay import ReplayError, replay
from sherlock.storage import dataset_dir, dataset_lock, folder_bytes


def undo_impact(rows_in: int, rows_out: int, diff) -> dict:
    """An undo's impact, all of it from the diff of the two versions: rows it quarantines
    again (undoing a restore) and rows it restores (undoing a quarantine) count, so the cascade sees
    that every widget's rows changed."""
    restored = sum(1 for r in diff.lineage if r[1] == "_row" and r[3] == "restored")
    return {"rows_in": rows_in, "rows_out": rows_out, "cells_changed": diff.cells_changed, "quarantined": diff.quarantined,
            "rows_restored": restored, "parse_failures": 0, "rows_added": len(diff.added_row_ids),
            "rows_deleted": len(diff.deleted_row_ids), "before_after": diff.before_after}


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
        summary = f"Undid step {target['no']}: {target['summary']}"
        if replay_nos:
            summary += f" (replayed {_nos(replay_nos)})"
        return _move(ctx, dataset, folder, current, remaining, target, "undo", summary,
                     UNDO_CODE.format(no=target["no"]), "Nothing was undone.")


def _move(ctx: Context, dataset: sqlite3.Row, folder, current: sqlite3.Row, chain_after: list[str], target: sqlite3.Row,
          kind: str, summary: str, code: str, nothing: str) -> dict:
    """The new current version whose effective chain is `chain_after`: an undo (the target left out) or a redo
    (the target back at the end). A version with exactly that chain is reused, so no data is rewritten; otherwise
    the longest prefix is replayed. Runs under the dataset lock."""
    db, dataset_id, step_id = ctx.db, dataset["id"], target["id"]
    remaining = chain_after
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
                f"Step {exc.step_no} couldn't be replayed: {exc.reason}. {nothing}",
                failed_step_id=exc.step_id, reason=exc.reason,
            ) from exc
        parquet, row_count, columns_json = relative, *_shape(folder / relative)
    else:
        parquet, row_count, columns_json = source["parquet_path"], source["row_count"], source["columns_json"]
    column_count = len([c for c in json.loads(columns_json) if c["name"] not in ("_row_id", "_quarantine_reason")])

    undo_id = new_id("stp")
    number = db.execute("SELECT coalesce(max(no), 0) + 1 FROM steps WHERE dataset_id = ?", (dataset_id,)).fetchone()[0]
    diff = diff_versions(folder / current["parquet_path"], folder / parquet)
    impact = undo_impact(current["row_count"], row_count, diff)
    now = now_iso()
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute(
            "INSERT INTO steps (id, dataset_id, no, kind, from_version, to_version, summary, column_targets_json, "
            "columns_added_json, columns_removed_json, notebook_code, impact_json, undone_step_id, "
            "replayed_step_ids_json, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, '[]', '[]', ?, ?, ?, ?, 'user', ?)",
            (undo_id, dataset_id, number, kind, current["version"], new_version, summary, target["column_targets_json"],
             code, json.dumps(impact), step_id,
             json.dumps([r.step_id for r in replayed]) if replayed else None, now),
        )
        db.execute(
            "INSERT INTO versions (dataset_id, version, parquet_path, row_count, column_count, columns_json, "
            "step_id, effective_step_ids_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (dataset_id, new_version, parquet, row_count, column_count, columns_json, undo_id,
             json.dumps(remaining), now),
        )
        if kind == "undo":
            dropped = db.execute("SELECT row_id, column FROM user_edited_cells WHERE dataset_id = ? AND step_id = ?",
                                 (dataset_id, step_id)).fetchall()
            db.execute("DELETE FROM user_edited_cells WHERE dataset_id = ? AND step_id = ?", (dataset_id, step_id))
        else:  # a redone edit batch protects its cells again (the Cleaner skips them)
            dropped = []
            if target["kind"] == "edit":
                db.execute("INSERT OR REPLACE INTO user_edited_cells (dataset_id, row_id, column, step_id) "
                           "SELECT DISTINCT dataset_id, row_id, column, step_id FROM lineage "
                           "WHERE dataset_id = ? AND step_id = ? AND column != '_row'", (dataset_id, step_id))
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


# --- the toolbar's Undo and Redo (docs/plans/chat-commands.md §4) -------------------------------------


def history(db: sqlite3.Connection, dataset_id: str, depth: int) -> dict:
    """What the toolbar's Undo and Redo would do now. Undo takes back the latest step in the current data, at most
    `depth` times in a row; Redo brings back what those undos took, newest first. Any other step (a command, an
    edit, the Cleaner, an undo of an older step from the Changes panel) starts a new history, so Redo is gone."""
    redo: list[str] = []
    streak = 0
    for s in db.execute("SELECT kind, undone_step_id, replayed_step_ids_json FROM steps WHERE dataset_id = ? ORDER BY no",
                        (dataset_id,)):
        if s["kind"] == "undo" and not s["replayed_step_ids_json"]:
            redo.append(s["undone_step_id"])
            streak += 1
        elif s["kind"] == "redo":
            if redo and redo[-1] == s["undone_step_id"]:
                redo.pop()
            streak = max(0, streak - 1)
        else:
            redo, streak = [], 0
    current = current_version_row(db, dataset_id)
    chain = json.loads(current["effective_step_ids_json"])

    def about(step_id: str | None) -> dict | None:
        row = db.execute("SELECT * FROM steps WHERE id = ?", (step_id,)).fetchone() if step_id else None
        return {"step_id": row["id"], "no": row["no"], "summary": row["summary"]} if row else None

    tail = db.execute("SELECT * FROM steps WHERE id = ?", (chain[-1],)).fetchone() if chain else None
    undo = about(tail["id"]) if tail is not None and not is_typing_step(tail) and streak < depth else None
    again = about(redo[-1]) if redo and redo[-1] not in chain else None
    return {"version": current["version"], "undo": undo, "redo": again, "depth_left": max(0, depth - streak)}


def quick_undo(ctx: Context, dataset_id: str, base_version: int) -> dict:
    """The toolbar's Undo: the latest step in the current data, so nothing is replayed and no data is rewritten."""
    h = history(ctx.db, dataset_id, ctx.settings.undo_depth)
    if h["undo"] is None:
        why = (f"You can undo up to {ctx.settings.undo_depth} changes in a row; older ones are in the Changes panel."
               if h["depth_left"] == 0 else "There's nothing to undo.")
        raise conflict(why, current_version=h["version"])
    return undo_step(ctx, dataset_id, h["undo"]["step_id"], base_version, confirm=True)


def redo_step(ctx: Context, dataset_id: str, base_version: int) -> dict:
    """The toolbar's Redo: the step the latest Undo took back, at the end of the chain again. That chain is the
    version before the undo, so its file is reused as it is."""
    db = ctx.db
    dataset = db.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
    folder = dataset_dir(ctx.settings, dataset["user_id"], dataset_id)
    with dataset_lock(folder):
        dataset = db.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
        if dataset["current_version"] != base_version:
            raise conflict(
                f"The data changed since you started (now version {dataset['current_version']}). Reload and try again.",
                current_version=dataset["current_version"],
            )
        h = history(db, dataset_id, ctx.settings.undo_depth)
        if h["redo"] is None:
            raise conflict("There's nothing to redo.", current_version=h["version"])
        target = db.execute("SELECT * FROM steps WHERE id = ?", (h["redo"]["step_id"],)).fetchone()
        current = current_version_row(db, dataset_id)
        chain = json.loads(current["effective_step_ids_json"]) + [target["id"]]
        return _move(ctx, dataset, folder, current, chain, target, "redo", f"Redid step {target['no']}: {target['summary']}",
                     REDO_CODE.format(no=target["no"]), "Nothing was redone.")
