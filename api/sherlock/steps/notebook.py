"""`notebook_code` for steps (TRD §6.7, Schema §2.5): the pandas that reproduces a step in the
exported notebook. Edit batches are rendered at commit time from their edit list.

Rendered code runs against `df` (the previous version, with `_row_id` and `_quarantine_reason`)
and leaves the next version in `df`.
"""

from collections import defaultdict

import pandas as pd

UNDO_CODE = "# Undo of step {no}: the exported notebook applies the version's effective chain instead.\n"


def typed(value, dtype: str):
    """A value converted to the column's DuckDB type, so `repr` writes a literal of that type."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    t = dtype.upper()
    try:
        if t in ("BIGINT", "INTEGER", "SMALLINT", "TINYINT", "HUGEINT", "UBIGINT"):
            return int(float(value)) if float(value).is_integer() else float(value)
        if t in ("DOUBLE", "FLOAT", "REAL") or t.startswith("DECIMAL"):
            return float(value)
        if t == "BOOLEAN":
            return str(value).strip().lower() in ("true", "t", "yes", "y", "1")
        if t == "DATE" or t.startswith("TIMESTAMP"):
            return pd.Timestamp(value)
    except (TypeError, ValueError):
        return str(value)
    return str(value)


def _literal(value) -> str:
    if isinstance(value, pd.Timestamp):
        return f"pd.Timestamp({value.isoformat()!r})"
    return repr(value)


def render_edit_batch(
    edits: list[dict],
    new_rows: list[dict],
    deleted_row_ids: list[int],
    restore_row_ids: list[int],
    dtypes: dict[str, str],
) -> str:
    """`edits`: [{row_id, column, value}]; `new_rows`: [{row_id, cells: {column: value}}] with the
    `_row_id` already assigned; `dtypes`: column → DuckDB type of the version being edited."""
    lines: list[str] = []
    by_column: dict[str, list[dict]] = defaultdict(list)
    for edit in edits:
        by_column[edit["column"]].append(edit)
    for column, column_edits in by_column.items():
        lines.append(f"# {column}: {len(column_edits)} cell(s) edited by hand")
        for edit in column_edits:
            value = typed(edit["value"], dtypes.get(column, "VARCHAR"))
            lines.append(f"df.loc[df._row_id == {int(edit['row_id'])}, {column!r}] = {_literal(value)}")
    if restore_row_ids:
        ids = sorted(int(i) for i in restore_row_ids)
        lines.append("# restored from quarantine")
        lines.append(f"df.loc[df._row_id.isin({ids}), '_quarantine_reason'] = None")
    if new_rows:
        records = []
        for row in new_rows:
            cells = {c: typed(v, dtypes.get(c, "VARCHAR")) for c, v in row["cells"].items()}
            body = ", ".join(f"{c!r}: {_literal(v)}" for c, v in cells.items())
            sep = ", " if body else ""
            records.append(f"    {{'_row_id': {int(row['row_id'])}, '_quarantine_reason': None{sep}{body}}},")
        lines.append(f"# {len(new_rows)} row(s) added by hand")
        lines.append("df = pd.concat([df, pd.DataFrame([")
        lines += records
        lines.append("])], ignore_index=True)")
    if deleted_row_ids:
        ids = sorted(int(i) for i in deleted_row_ids)
        lines.append("# rows deleted by hand (a real deletion, unlike quarantine)")
        lines.append(f"df = df[~df._row_id.isin({ids})]")
    return "\n".join(lines) + "\n"


def validate_notebook_code(kind: str, code: str) -> None:
    """Schema §7: every step has notebook_code; clean and computed_column steps end with `df = result`."""
    if not code or not code.strip():
        raise ValueError("notebook_code is required on every step")
    if kind in ("clean", "computed_column") and code.rstrip().splitlines()[-1].strip() != "df = result":
        raise ValueError(f"a {kind} step's notebook_code must end with `df = result`")
