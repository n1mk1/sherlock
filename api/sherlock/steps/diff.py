"""Cell-level diff between two versions by `_row_id`: the lineage rows of a step (Schema §2.6).

A cell counts as changed only if its value changed: when a column's type changed (the typing
step), the old value is cast to the new type before comparing, so `'22'` → `22` is not a change,
while a value that fails the cast (or a sentinel that became NULL) is. A cell that lost its value
in a row the same step quarantined gets the flag `quarantined`: its original text is kept here.
"""

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from sherlock.storage import sql_path

SYSTEM = ("_row_id", "_quarantine_reason")
BEFORE_AFTER = 20


def _ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


@dataclass
class Diff:
    rows_in: int
    rows_out: int
    columns_added: list[str]
    columns_removed: list[str]
    changed_columns: list[str]
    lineage: list[tuple] = field(default_factory=list)  # (row_id, column, old, new, flag)
    cells_changed: int = 0
    quarantined: int = 0
    added_row_ids: list[int] = field(default_factory=list)
    deleted_row_ids: list[int] = field(default_factory=list)

    @property
    def before_after(self) -> list[dict]:
        """Up to 20 changed cells: one example of each distinct (column, old → new) pair, the most frequent pair first
        (ties in row order), then further cells in row order. So a preview shows every kind of change before repeats."""
        cells = sorted((r for r in self.lineage if r[1] != "_row"), key=lambda r: r[0])
        count = Counter((r[1], r[2], r[3]) for r in cells)
        firsts: dict[tuple, tuple] = {}
        for r in cells:
            firsts.setdefault((r[1], r[2], r[3]), r)
        picked = sorted(firsts.values(), key=lambda r: -count[(r[1], r[2], r[3])])[:BEFORE_AFTER]  # stable: ties keep row order
        seen = {id(r) for r in picked}
        cells = picked + [r for r in cells if id(r) not in seen][:BEFORE_AFTER - len(picked)]
        return [{"row_id": r[0], "column": r[1], "old": r[2], "new": r[3]} for r in cells]


def diff_versions(old: Path, new: Path) -> Diff:
    conn = duckdb.connect(":memory:")
    try:
        conn.execute(f"CREATE VIEW o AS SELECT * FROM read_parquet({sql_path(old)})")
        conn.execute(f"CREATE VIEW n AS SELECT * FROM read_parquet({sql_path(new)})")
        old_types = {r[0]: r[1] for r in conn.execute("DESCRIBE o").fetchall()}
        new_types = {r[0]: r[1] for r in conn.execute("DESCRIBE n").fetchall()}
        rows_in = conn.execute("SELECT count(*) FROM o").fetchone()[0]
        rows_out = conn.execute("SELECT count(*) FROM n").fetchone()[0]
        old_cols = [c for c in old_types if c not in SYSTEM]
        new_cols = [c for c in new_types if c not in SYSTEM]
        shared = [c for c in new_cols if c in old_types]
        diff = Diff(
            rows_in=rows_in,
            rows_out=rows_out,
            columns_added=[c for c in new_cols if c not in old_types],
            columns_removed=[c for c in old_cols if c not in new_types],
            changed_columns=[],
        )

        for col in shared:
            old_expr = f"o.{_ident(col)}"
            if old_types[col] != new_types[col]:
                old_expr = f"TRY_CAST(o.{_ident(col)} AS {new_types[col]})"
            rows = conn.execute(
                f"SELECT o._row_id, o.{_ident(col)}::VARCHAR, n.{_ident(col)}::VARCHAR, "
                "o._quarantine_reason IS NULL AND n._quarantine_reason IS NOT NULL "
                f"FROM o JOIN n USING (_row_id) WHERE {old_expr} IS DISTINCT FROM n.{_ident(col)} "
                f"OR (o.{_ident(col)} IS NOT NULL AND n.{_ident(col)} IS NULL) "
                "ORDER BY o._row_id"
            ).fetchall()
            if rows:
                diff.changed_columns.append(col)
                diff.lineage += [
                    (r[0], col, r[1], r[2], "quarantined" if r[3] and r[2] is None else None) for r in rows
                ]
        diff.cells_changed = len(diff.lineage)

        quarantined = conn.execute(
            "SELECT n._row_id, n._quarantine_reason FROM o JOIN n USING (_row_id) "
            "WHERE o._quarantine_reason IS NULL AND n._quarantine_reason IS NOT NULL ORDER BY 1"
        ).fetchall()
        restored = conn.execute(
            "SELECT n._row_id FROM o JOIN n USING (_row_id) "
            "WHERE o._quarantine_reason IS NOT NULL AND n._quarantine_reason IS NULL ORDER BY 1"
        ).fetchall()
        added = conn.execute("SELECT _row_id FROM n ANTI JOIN o USING (_row_id) ORDER BY 1").fetchall()
        deleted = conn.execute("SELECT _row_id FROM o ANTI JOIN n USING (_row_id) ORDER BY 1").fetchall()

        diff.quarantined = len(quarantined)
        diff.lineage += [(r[0], "_row", None, "quarantined", "quarantined") for r in quarantined]
        diff.lineage += [(r[0], "_row", None, "restored", None) for r in restored]
        diff.lineage += [(r[0], "_row", None, "added", None) for r in added]
        diff.lineage += [(r[0], "_row", None, "deleted", None) for r in deleted]
        diff.added_row_ids = [r[0] for r in added]
        diff.deleted_row_ids = [r[0] for r in deleted]
        return diff
    finally:
        conn.close()


def check_version_file(path: Path) -> tuple[int, int | None]:
    """A version must carry a unique, non-null `_row_id` and a `_quarantine_reason` column.
    Returns (rows, max _row_id)."""
    conn = duckdb.connect(":memory:")
    try:
        conn.execute(f"CREATE VIEW v AS SELECT * FROM read_parquet({sql_path(path)})")
        columns = {r[0] for r in conn.execute("DESCRIBE v").fetchall()}
        missing = [c for c in SYSTEM if c not in columns]
        if missing:
            raise ValueError(f"the new version lacks {', '.join(missing)}")
        rows, distinct, nulls, top = conn.execute(
            "SELECT count(*), count(DISTINCT _row_id), count(*) - count(_row_id), max(_row_id) FROM v"
        ).fetchone()
        if nulls or distinct != rows:
            raise ValueError("_row_id must be unique and never empty")
        return rows, top
    finally:
        conn.close()
