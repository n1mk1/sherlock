"""Per-column stats, histograms (20 bins), top values (10) and sample values (TRD §7.1 step 3)."""

import math

import numpy as np
import pandas as pd

from sherlock.profile.infer import NUMERIC_TYPES, Column

HISTOGRAM_BINS = 20
TOP_VALUES = 10
SAMPLE_VALUES = 3


def _num(value) -> float | int | None:
    if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
        return None
    as_float = float(value)
    return int(as_float) if as_float.is_integer() else round(as_float, 6)


def numeric_stats(col: Column) -> dict | None:
    values = col.numeric.dropna() if col.numeric is not None else pd.Series(dtype=float)
    values = values[np.isfinite(values)]
    if values.empty:
        return None
    return {
        "min": _num(values.min()),
        "max": _num(values.max()),
        "mean": _num(values.mean()),
        "median": _num(values.median()),
        "p05": _num(values.quantile(0.05)),
        "p95": _num(values.quantile(0.95)),
    }


def date_stats(col: Column) -> dict | None:
    values = col.dates.dropna() if col.dates is not None else pd.Series(dtype="datetime64[ns]")
    if values.empty:
        return None
    fmt = "%Y-%m-%dT%H:%M:%S" if col.type == "datetime" else "%Y-%m-%d"
    return {"min": values.min().strftime(fmt), "max": values.max().strftime(fmt), "format": col.date_format}


def histogram(col: Column) -> dict | None:
    if col.type not in NUMERIC_TYPES or col.numeric is None:
        return None
    values = col.numeric.dropna()
    values = values[np.isfinite(values)]
    if values.empty:
        return None
    counts, edges = np.histogram(values, bins=HISTOGRAM_BINS)
    return {"bins": [_num(e) for e in edges], "counts": [int(c) for c in counts]}


def top_values(col: Column) -> list[dict] | None:
    if col.type in NUMERIC_TYPES and col.role == "measure":
        return None
    if col.type in ("text", "id", "empty"):
        return None
    counts = col.raw.dropna().astype(str).value_counts().head(TOP_VALUES)
    return [{"value": value, "count": int(count)} for value, count in counts.items()]


def sample_values(col: Column) -> list:
    """Up to three distinct values, typed (numbers as numbers), in file order."""
    if col.type in NUMERIC_TYPES and col.numeric is not None:
        return [_num(v) for v in col.numeric.dropna().drop_duplicates().head(SAMPLE_VALUES)]
    return [str(v) for v in col.text.drop_duplicates().head(SAMPLE_VALUES)]


def column_stats(col: Column) -> dict | None:
    if col.type in NUMERIC_TYPES:
        return numeric_stats(col)
    if col.type in ("date", "datetime"):
        return date_stats(col)
    if col.type in ("text", "id", "category"):
        lengths = col.text.str.len()
        return {"min_length": int(lengths.min()), "max_length": int(lengths.max()),
                "mean_length": _num(lengths.mean())} if not lengths.empty else None
    return None
