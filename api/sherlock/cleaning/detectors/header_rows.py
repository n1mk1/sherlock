"""Header rows: the column names repeated as a row inside the data, as when exports are pasted one
under another. A row is one when at least half its columns (two or more) hold their own column's name.
Examples are `_row_id`s."""

import math

import pandas as pd

from sherlock.cleaning.detectors.base import DetectorSpec, Finding, Frame, Injector
from sherlock.cleaning.detectors.fixtures import clean_frame

SHARE = 0.5


def detect(frame: Frame) -> list[Finding]:
    if len(frame.columns) < 2 or frame.df.empty:
        return []
    needed = max(2, math.ceil(SHARE * len(frame.columns)))
    matches = pd.Series(0, index=frame.df.index)
    for name, col in frame.columns.items():
        own = col.text.str.casefold() == name.strip().casefold()
        matches.loc[own[own].index] += 1
    rows = matches[matches >= needed].index
    if not len(rows):
        return []
    return [Finding(
        "header_rows", None, len(rows), "Quarantine the rows that repeat the column names.",
        [int(i) for i in rows[:5]], {},
    )]


def damage(df, column: str, rows: list[int], rng) -> dict:
    """Each chosen row's cells replaced by their column names."""
    return {(i, c): c for i in rows for c in df.columns}


SPEC = DetectorSpec(
    "header_rows", "repeated header rows", "Rows inside the data that repeat the column names.",
    group="records", weight=0.8, default_level="breaks", scope="rows", detect=detect, depth=3,
    injectors={"header": Injector(damage, share=0.03)}, clean_fixture=lambda: (clean_frame(), "record_id"),
)
