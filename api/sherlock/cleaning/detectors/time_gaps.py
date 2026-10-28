"""Gaps in a regular series: a date column with one row per day, week or month, from which some periods
are missing. Counted in missing periods. Never changed: a missing period can't be filled without making
up rows, so the gap is reported and left as it is."""

import pandas as pd

from sherlock.cleaning.detectors.base import DetectorSpec, Finding, Frame
from sherlock.cleaning.detectors.fixtures import clean_frame

MIN_DATES = 20
UNIQUE = 0.9    # one row per period, not a log of events
REGULAR = 0.8   # the share of steps that are exactly one period


def _missing(points: list, steps: list[int], step: int, at) -> list:
    """The periods between consecutive points that are more than one step apart; `at(point, k)` is the
    point k steps after."""
    return [at(points[i - 1], k) for i in range(1, len(points)) if steps[i - 1] > step
            for k in range(1, steps[i - 1] // step)]


def _gaps(dates: pd.Series) -> tuple[str, list[pd.Timestamp]] | None:
    days = sorted(dates.dt.normalize().unique())
    if len(days) < 2:
        return None
    steps = [int((b - a) / pd.Timedelta(days=1)) for a, b in zip(days, days[1:])]
    step = int(pd.Series(steps).mode().iloc[0])
    if step in (1, 7) and steps.count(step) / len(steps) >= REGULAR:
        return ("day" if step == 1 else "week"), _missing(days, steps, step, lambda d, k: d + pd.Timedelta(days=step * k))
    months = sorted({pd.Timestamp(d).to_period("M") for d in days})
    if 28 <= step <= 31 and len(months) == len(days):
        jumps = [b.ordinal - a.ordinal for a, b in zip(months, months[1:])]
        if jumps.count(1) / len(jumps) >= REGULAR:
            return "month", _missing(months, jumps, 1, lambda m, k: (m + k).to_timestamp())
    return None


def detect(frame: Frame) -> list[Finding]:
    findings = []
    for name, col in frame.columns.items():
        if col.type not in ("date", "datetime") or col.dates is None:
            continue
        dates = col.dates.dropna()
        if len(dates) < MIN_DATES or dates.dt.normalize().nunique() / len(dates) < UNIQUE:
            continue
        found = _gaps(dates)
        if found is None or not found[1]:
            continue
        step, missing = found
        shown = [d.strftime("%Y-%m") if step == "month" else d.date().isoformat() for d in missing[:5]]
        findings.append(Finding(
            "time_gaps", name, len(missing),
            f"Leave the gaps as they are; a missing {step} is reported, never filled with made-up rows.",
            shown, {"step": step},
        ))
    return findings


def found_fixture():
    """A daily series of readings with some days missing."""
    df = clean_frame(rows=60)
    days = [d for d in pd.date_range("2022-03-01", periods=70, freq="D") if d.day not in (5, 6, 19, 27)][:60]
    df.insert(len(df.columns) - 1, "reading_date", [d.date().isoformat() for d in days])
    return df


SPEC = DetectorSpec(
    "time_gaps", "gaps in a regular series", "Days, weeks or months missing from a date column with one row per period.",
    group="other", weight=0.3, default_level=None, scope="column", detect=detect, depth=5,
    applies_to=frozenset(("date", "datetime")),
    never_change="Gaps in a regular series are reported, never filled with made-up rows", skip_text="gaps left as they are",
    found_fixture=found_fixture,
)
