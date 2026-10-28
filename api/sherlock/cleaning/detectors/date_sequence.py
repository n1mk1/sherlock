"""Dates out of their usual order: two date columns where one is on or after the other in almost every
row (ordered, then shipped), read from the data rather than the names, and a few rows where it is
before. Pairs whose names already say their order (start and end, …) are the cross-column detector's."""

from itertools import permutations

import pandas as pd

from sherlock.cleaning.detectors.base import DetectorSpec, Finding, Frame, Injector
from sherlock.cleaning.detectors.cross_column import earlier
from sherlock.cleaning.detectors.fixtures import clean_frame

AGREEMENT = 0.98  # dates near each other can be in one order this often by chance below it
MIN_ROWS = 20
MAX_COLUMNS = 8


def detect(frame: Frame) -> list[Finding]:
    dates = {n: c.dates for n, c in frame.columns.items()
             if c.type in ("date", "datetime") and c.dates is not None}
    names = list(dates)[:MAX_COLUMNS]
    findings = []
    for first, later in permutations(names, 2):
        if earlier(frame.columns, later) == first or earlier(frame.columns, first) == later:
            continue
        a, b = dates[first], dates[later]
        known = a.notna() & b.notna()
        if known.sum() < MIN_ROWS:
            continue
        in_order = b[known] >= a[known]
        if not AGREEMENT <= in_order.mean() < 1 or (b[known] > a[known]).mean() < 0.5:
            continue
        off = in_order[~in_order].index
        findings.append(Finding(
            "date_sequence", later, len(off),
            f"{later} is on or after {first} in almost every row; review the rows where it is before.",
            [int(i) for i in off[:5]], {"earlier": first, "agreement": round(float(in_order.mean()), 4)},
        ))
    return findings


def clean_fixture():
    """An order date a few days before the start, and a shipping date ten to forty days after the order."""
    df = clean_frame()
    start = pd.to_datetime(df["start_date"])
    ordered = [d - pd.Timedelta(days=1 + i % 5) for i, d in enumerate(start)]
    shipped = [d + pd.Timedelta(days=10 + i * 7 % 31) for i, d in enumerate(ordered)]
    df.insert(len(df.columns) - 1, "ordered_on", [d.date().isoformat() for d in ordered])
    df.insert(len(df.columns) - 1, "shipped_on", [d.date().isoformat() for d in shipped])
    return df, "shipped_on"


def damage(df, column: str, rows: list[int], rng) -> dict:
    """Each chosen date moved to a day before the date it follows (`ordered_on` in the fixture, else the
    column before it)."""
    position = list(df.columns).index(column)
    before = "ordered_on" if "ordered_on" in df.columns else df.columns[position - 1]
    return {(i, column): (pd.Timestamp(df.at[i, before]) - pd.Timedelta(days=1)).date().isoformat() for i in rows}


SPEC = DetectorSpec(
    "date_sequence", "dates out of their usual order",
    "Rows where a date comes before another date it follows in almost every other row.",
    group="records", weight=0.5, default_level="check", scope="columns", detect=detect, depth=4,
    applies_to=frozenset(("date", "datetime")),
    injectors={"early": Injector(damage, share=0.015)}, clean_fixture=clean_fixture,
)
