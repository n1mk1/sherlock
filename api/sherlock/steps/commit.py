"""`commit_step` (TRD §7.8, Schema §7): the only way a dataset gets a new version.

Under the dataset lock: check `base_version`, let the caller write the new Parquet, check it,
diff it against the current version (lineage), then in one SQLite transaction write the step,
the version (with its effective chain), the lineage, `user_edited_cells` for edit batches, and
bump `current_version`, `next_row_id`, `state_rev` and storage. Then re-profile the new version,
emit `version.created` (TRD §5.1) and mark the ML runs the change outdates (TRD §7.5).
"""

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sherlock.config import Settings
from sherlock.db.util import new_id, now_iso
from sherlock.errors import ApiError
from sherlock.jobs.events import EventBus, emit
from sherlock.profile import service as profile_service
from sherlock.steps.diff import check_version_file, diff_versions
from sherlock.steps.notebook import validate_notebook_code
from sherlock.storage import VersionConnections, dataset_dir, dataset_lock, folder_bytes

KINDS = ("clean", "edit", "undo", "ml_column", "computed_column")
CREATORS = ("system", "cleaner", "user", "chat")
ROW_PRESERVING = ("clean", "ml_column", "computed_column")


@dataclass
class StepSpec:
    kind: str
    summary: str
    created_by: str
    notebook_code: str
    column_targets: list[str] = field(default_factory=list)
    code: str | None = None
    edits: dict | None = None
    helpers_used: list[str] = field(default_factory=list)
    confidence: float | None = None
    gate: str | None = None
    flag_reason: str | None = None
    decisions: list[dict] = field(default_factory=list)
    verifiers: dict = field(default_factory=dict)
    parse_failures: int = 0
    job_id: str | None = None
    # (row_id, column) → (new_value, flag) replacing the diff's lineage row, e.g. an edit whose
    # value didn't parse as the column's type: the cell is NULL, lineage keeps the text, flag `invalid`.
    cell_overrides: dict[tuple[int, str], tuple[str | None, str | None]] = field(default_factory=dict)


@dataclass
class Context:
    settings: Settings
    db: sqlite3.Connection
    cache: VersionConnections
    bus: EventBus | None = None


def emit_version_created(ctx: Context, dataset: sqlite3.Row, step: dict, version: int) -> None:
    impact = step["impact"]
    emit(ctx.db, ctx.bus, dataset["id"], dataset["user_id"], "version.created", {
        "version": version, "step_id": step["id"], "summary": step["summary"],
        "cells_changed": impact["cells_changed"], "rows_added": impact["rows_added"],
        "rows_removed": impact["rows_deleted"],
    }, job_id=step["job_id"])
    from sherlock.ml import runner as ml
    from sherlock.steps.lineage import changes

    fresh = ctx.db.execute("SELECT * FROM datasets WHERE id = ?", (dataset["id"],)).fetchone()
    ml.outdate(ctx.db, ctx.bus, fresh, lambda since: changes(ctx.db, fresh["id"], since, version), step["job_id"])


def conflict(message: str, **extra) -> ApiError:
    return ApiError(409, "conflict", message, extra=extra)


def current_version_row(db: sqlite3.Connection, dataset_id: str) -> sqlite3.Row:
    return db.execute(
        "SELECT v.* FROM versions v JOIN datasets d ON d.id = v.dataset_id AND v.version = d.current_version "
        "WHERE d.id = ?",
        (dataset_id,),
    ).fetchone()


def _check_spec(spec: StepSpec) -> None:
    if spec.kind not in KINDS or spec.kind == "undo":
        raise ValueError(f"commit_step can't make a {spec.kind!r} step")
    if spec.created_by not in CREATORS:
        raise ValueError(f"unknown created_by {spec.created_by!r}")
    validate_notebook_code(spec.kind, spec.notebook_code)


def commit_step(
    ctx: Context,
    dataset_id: str,
    base_version: int,
    spec: StepSpec,
    produce: Callable[[Path, Path], None],
) -> tuple[dict, int]:
    """`produce(current_parquet, out_parquet)` must write the new version. Returns (step, version)."""
    _check_spec(spec)
    dataset = ctx.db.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
    folder = dataset_dir(ctx.settings, dataset["user_id"], dataset_id)
    with dataset_lock(folder):
        dataset = ctx.db.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
        if dataset["current_version"] != base_version:
            raise conflict(
                f"The data changed since you started (now version {dataset['current_version']}). Reload and try again.",
                current_version=dataset["current_version"],
            )
        parent = current_version_row(ctx.db, dataset_id)
        new_version = base_version + 1
        relative = f"versions/v{new_version}.parquet"
        out = folder / relative
        out.unlink(missing_ok=True)
        try:
            produce(folder / parent["parquet_path"], out)
            rows, max_row_id = check_version_file(out)
            diff = diff_versions(folder / parent["parquet_path"], out)
            if spec.kind in ROW_PRESERVING and (diff.added_row_ids or diff.deleted_row_ids):
                raise ValueError("a cleaning step may not add or remove rows (quarantine them instead)")
            if diff.added_row_ids and min(diff.added_row_ids) < dataset["next_row_id"]:
                raise ValueError("new rows must take fresh _row_ids from next_row_id")
            step = _write(ctx, dataset, parent, new_version, relative, spec, diff, rows, max_row_id, folder)
        except Exception:
            out.unlink(missing_ok=True)
            raise
    dataset = _dataset(ctx, dataset_id)
    profile_service.get_or_build(ctx.settings, ctx.db, ctx.cache, dataset, new_version)
    emit_version_created(ctx, dataset, step, new_version)
    return step, new_version


def _dataset(ctx: Context, dataset_id: str) -> sqlite3.Row:
    return ctx.db.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()


def _write(ctx, dataset, parent, new_version, relative, spec, diff, rows, max_row_id, folder) -> dict:
    db = ctx.db
    now = now_iso()
    step_id = new_id("stp")
    number = db.execute("SELECT coalesce(max(no), 0) + 1 FROM steps WHERE dataset_id = ?", (dataset["id"],)).fetchone()[0]
    columns = [{"name": name, "type": kind} for name, kind in _schema(folder / relative)]
    effective = json.loads(parent["effective_step_ids_json"]) + [step_id]
    impact = {
        "rows_in": diff.rows_in,
        "rows_out": diff.rows_out,
        "cells_changed": diff.cells_changed,
        "quarantined": diff.quarantined,
        "parse_failures": spec.parse_failures,
        "rows_added": len(diff.added_row_ids),
        "rows_deleted": len(diff.deleted_row_ids),
        "before_after": diff.before_after,
    }
    targets = spec.column_targets or diff.changed_columns
    lineage = _lineage_rows(diff.lineage, spec)
    user_columns = [c for c in columns if c["name"] not in ("_row_id", "_quarantine_reason")]
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute(
            "INSERT INTO steps (id, dataset_id, no, kind, from_version, to_version, summary, column_targets_json, "
            "columns_added_json, columns_removed_json, code, edits_json, notebook_code, helpers_used_json, impact_json, "
            "confidence, gate, flag_reason, decisions_json, verifiers_json, created_by, job_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (step_id, dataset["id"], number, spec.kind, parent["version"], new_version, spec.summary,
             json.dumps(targets), json.dumps(diff.columns_added), json.dumps(diff.columns_removed), spec.code,
             json.dumps(spec.edits) if spec.edits is not None else None, spec.notebook_code,
             json.dumps(spec.helpers_used), json.dumps(impact), spec.confidence, spec.gate, spec.flag_reason,
             json.dumps(spec.decisions), json.dumps(spec.verifiers), spec.created_by, spec.job_id, now),
        )
        db.execute(
            "INSERT INTO versions (dataset_id, version, parquet_path, row_count, column_count, columns_json, "
            "step_id, effective_step_ids_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (dataset["id"], new_version, relative, rows, len(user_columns), json.dumps(columns), step_id,
             json.dumps(effective), now),
        )
        db.executemany(
            "INSERT INTO lineage (dataset_id, step_id, row_id, column, old_value, new_value, flag, version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [(dataset["id"], step_id, r[0], r[1], r[2], r[3], r[4], new_version) for r in lineage],
        )
        if spec.kind == "edit":
            db.executemany(
                "INSERT OR REPLACE INTO user_edited_cells (dataset_id, row_id, column, step_id) VALUES (?, ?, ?, ?)",
                [(dataset["id"], r[0], r[1], step_id) for r in lineage if r[1] != "_row"],
            )
        size = folder_bytes(folder)
        db.execute(
            "UPDATE datasets SET current_version = ?, row_count = ?, column_count = ?, "
            "next_row_id = max(next_row_id, ?), state_rev = state_rev + 1, folder_bytes = ? WHERE id = ?",
            (new_version, rows, len(user_columns), (max_row_id or 0) + 1, size, dataset["id"]),
        )
        db.execute(
            "UPDATE users SET storage_bytes = storage_bytes + ? WHERE id = ?",
            (size - dataset["folder_bytes"], dataset["user_id"]),
        )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    return load_step(db, step_id)


def _lineage_rows(rows: list[tuple], spec: StepSpec) -> list[tuple]:
    """The diff's lineage with the step's overrides applied; cells of a flagged step get `flagged`."""
    out = []
    seen = set()
    for row_id, column, old, new, flag in rows:
        key = (row_id, column)
        if key in spec.cell_overrides:
            new, flag = spec.cell_overrides[key]
            seen.add(key)
        elif flag is None and column != "_row" and spec.gate == "flag":
            flag = "flagged"
        out.append((row_id, column, old, new, flag))
    # An override for a cell the diff didn't see (an invalid edit of a cell that was already NULL).
    for (row_id, column), (new, flag) in spec.cell_overrides.items():
        if (row_id, column) not in seen:
            out.append((row_id, column, None, new, flag))
    return out


def _schema(path: Path) -> list[tuple[str, str]]:
    import duckdb

    from sherlock.storage import sql_path

    conn = duckdb.connect(":memory:")
    try:
        return [(r[0], r[1]) for r in conn.execute(f"DESCRIBE SELECT * FROM read_parquet({sql_path(path)})").fetchall()]
    finally:
        conn.close()


def load_step(db: sqlite3.Connection, step_id: str) -> dict:
    """A step in the TRD §6.2 shape."""
    r = db.execute("SELECT * FROM steps WHERE id = ?", (step_id,)).fetchone()
    return {
        "id": r["id"], "dataset_id": r["dataset_id"], "no": r["no"], "kind": r["kind"],
        "from_version": r["from_version"], "to_version": r["to_version"], "summary": r["summary"],
        "column_targets": json.loads(r["column_targets_json"]),
        "columns_added": json.loads(r["columns_added_json"]),
        "columns_removed": json.loads(r["columns_removed_json"]),
        "code": r["code"], "edits": json.loads(r["edits_json"]) if r["edits_json"] else None,
        "notebook_code": r["notebook_code"],
        "impact": json.loads(r["impact_json"]), "confidence": r["confidence"], "gate": r["gate"],
        "flag_reason": r["flag_reason"], "decisions": json.loads(r["decisions_json"]),
        "verifiers": json.loads(r["verifiers_json"]),
        "undone_step_id": r["undone_step_id"],
        "replayed_step_ids": json.loads(r["replayed_step_ids_json"]) if r["replayed_step_ids_json"] else None,
        "created_by": r["created_by"], "job_id": r["job_id"], "created_at": r["created_at"],
    }
