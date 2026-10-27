"""Seeded clean frames for the detector contract suite (TRD §14): data no rated detector finds anything
in, of every column type, as an uploaded CSV gives it (text cells, None for missing). The names and
values are placeholders, never a sample file's (Rule 4)."""

import numpy as np
import pandas as pd

CATEGORIES = ["Alpha", "Bravo", "Charlie", "Delta"]


def clean_frame(rows: int = 200, seed: int = 7) -> pd.DataFrame:
    """An ID, a measure, a count, a category, a date pair in order and a yes/no column, independent of
    each other."""
    rng = np.random.default_rng(seed)
    start = pd.Timestamp("2021-01-01") + pd.to_timedelta(rng.integers(0, 60, rows), unit="D")
    end = start + pd.to_timedelta(rng.integers(1, 30, rows), unit="D")
    return pd.DataFrame({
        "record_id": [f"R{10000 + i}" for i in range(rows)],
        "amount": [f"{v:.2f}" for v in rng.normal(50, 8, rows)],
        "units": [str(v) for v in rng.integers(1, 21, rows)],
        "category": rng.choice(CATEGORIES, rows).tolist(),
        "start_date": [d.date().isoformat() for d in start],
        "end_date": [d.date().isoformat() for d in end],
        "flag": rng.choice(["yes", "no"], rows).tolist(),
    }, dtype=object)


def with_column(name: str, values: list, rows: int = 200, seed: int = 7) -> pd.DataFrame:
    """The clean frame with one more column, before its last (the yes/no column stays the target)."""
    df = clean_frame(rows, seed)
    df.insert(len(df.columns) - 1, name, values)
    return df
