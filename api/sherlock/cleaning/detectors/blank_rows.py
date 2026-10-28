"""Blank rows: rows with no value in any column (empty cells and placeholders only), left by a
spreadsheet export or a pasted range. They count as records though they hold none. Only checked in a
file of two columns or more; in one column they are missing values. Examples are `_row_id`s."""

import pandas as pd

from sherlock.cleaning.detectors.base import DetectorSpec, Finding, Frame, Injector
from sherlock.cleaning.detectors.fixtures import clean_frame


def detect(frame: Frame) -> list[Finding]:
    if len(frame.columns) < 2 or frame.df.empty:
        return []
    filled = pd.Series(False, index=frame.df.index)
    for col in frame.columns.values():
        filled.loc[col.text.index] = True
    blank = filled[~filled].index
    if not len(blank):
        return []
    return [Finding(
        "blank_rows", None, len(blank), "Quarantine the rows that are empty in every column.",
        [int(i) for i in blank[:5]], {},
    )]


def damage(df, column: str, rows: list[int], rng) -> dict:
    """Every cell of each chosen row emptied."""
    return {(i, c): None for i in rows for c in df.columns if df.at[i, c] is not None}


SPEC = DetectorSpec(
    "blank_rows", "empty rows", "Rows with no value in any column.",
    group="records", weight=0.5, default_level="skews", scope="rows", detect=detect, depth=3,
    injectors={"blank": Injector(damage, share=0.03)}, clean_fixture=lambda: (clean_frame(), "record_id"),
)
