"""Build a version's DataCard (TRD §6.1, §7.1 steps 3–4): types, roles, stats, issues.

Quarantined rows are left out: the card describes the rows that widgets, ML and stories use,
and reports how many were set aside.
"""

import json
from datetime import datetime

import duckdb
import numpy as np
import pandas as pd

from sherlock.cleaning.detectors import Frame, run_all
from sherlock.cleaning.detectors.unit_mixes import WITH_UNIT
from sherlock.db.util import new_id
from sherlock.profile import stats
from sherlock.profile.infer import Column, as_text, infer_role, infer_type

SYSTEM_COLUMNS = ("_row_id", "_quarantine_reason")


def load_frame(conn: duckdb.DuckDBPyConnection) -> tuple[pd.DataFrame, dict[str, str], int]:
    """The version's usable rows as a DataFrame indexed by `_row_id`, the column types, and the
    number of quarantined rows."""
    types = {name: str(kind) for name, kind, *_ in conn.execute("DESCRIBE t").fetchall()}
    quarantined = conn.execute("SELECT count(*) FROM t WHERE _quarantine_reason IS NOT NULL").fetchone()[0]
    df = conn.execute("SELECT * FROM t WHERE _quarantine_reason IS NULL ORDER BY _row_id").df()
    df = df.set_index("_row_id").drop(columns=["_quarantine_reason"])
    df = df.astype(object).where(df.notna(), None)
    return df, {k: v for k, v in types.items() if k not in SYSTEM_COLUMNS}, int(quarantined)


def build_frame(df: pd.DataFrame, types: dict[str, str]) -> Frame:
    columns: dict[str, Column] = {}
    names = list(df.columns)
    for position, name in enumerate(names):
        col = Column(name=name, raw=df[name], text=as_text(df[name]))
        infer_type(col, types.get(name))
        infer_role(col, is_last=position == len(names) - 1)
        columns[name] = col
    from sherlock.ml.registry import target_ok

    # An outcome is a column a driver analysis can explain: not free text that repeats a few values.
    targets = [n for n, c in columns.items() if c.role == "target_like" and target_ok(
        {"role": c.role, "type": c.type, "distinct": c.distinct, "stats": stats.column_stats(c)})]
    return Frame(df=df, columns=columns, target_candidates=targets)


def _unit(col: Column) -> str | None:
    if col.type not in ("category", "text") or col.text.empty:
        return None
    units = col.text.str.extract(WITH_UNIT)[0].str.lower()
    if units.notna().mean() >= 0.99 and units.nunique() == 1:
        return units.dropna().iloc[0]
    return None


def column_entry(col: Column, rows: int) -> dict:
    return {
        "name": col.name,
        "type": col.type,
        "role": col.role,
        "missing": col.missing,
        "missing_pct": round(100 * col.missing / rows, 2) if rows else 0.0,
        "distinct": col.distinct,
        "stats": stats.column_stats(col),
        "top_values": stats.top_values(col),
        "sample_values": stats.sample_values(col),
        "flags": list(col.flags),
        "unit": _unit(col),
        "semantic": None,
        "histogram": stats.histogram(col),
    }


def build_datacard(conn: duckdb.DuckDBPyConnection, version: int) -> tuple[dict, Frame]:
    df, types, quarantined = load_frame(conn)
    frame = build_frame(df, types)
    issues = []
    leakage = []
    for finding, severity in run_all(frame):
        issue = {
            "id": new_id("iss"),
            "detector": finding.detector,
            "column": finding.column,
            "count": finding.count,
            "severity": severity,
            "proposal": finding.proposal,
            "examples": finding.examples,
            "details": finding.details,
        }
        issues.append(issue)
        if finding.detector == "leakage":
            leakage.append({"column": finding.column, "target": finding.details["target"],
                            "reason": finding.details["reason"]})
    card = {
        "version": version,
        "row_count": frame.rows,
        "column_count": len(frame.columns),
        "quarantined": quarantined,
        "columns": [column_entry(c, frame.rows) for c in frame.columns.values()],
        "issues": issues,
        "target_candidates": frame.target_candidates,
        "time_columns": [n for n, c in frame.columns.items() if c.role == "time"],
        "id_columns": [n for n, c in frame.columns.items() if c.role == "id"],
        "leakage_candidates": leakage,
    }
    return json.loads(json.dumps(card, default=_plain)), frame


def _plain(value):
    """numpy scalars and timestamps as plain JSON values."""
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return str(value)
