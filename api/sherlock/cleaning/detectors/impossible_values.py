"""Impossible values: negatives in quantities that can't be negative, ages over 120, percentages
outside 0–100, and dates in the future or before 1800. Quantities are recognised by column name."""

import re

import pandas as pd

from sherlock.cleaning.detectors.base import Finding, Frame, examples
from sherlock.profile.infer import NUMERIC_TYPES

NON_NEGATIVE = re.compile(
    r"(age|price|fare|amount|cost|count|qty|quantity|weight|height|salary|income|wage|duration|"
    r"distance|size|length|width|area|population|total|revenue|sales|units|stock|years?)", re.I)
AGE = re.compile(r"(^|_|\b)age($|_|\b)", re.I)
PERCENT = re.compile(r"(pct|percent|percentage)", re.I)
MAX_AGE = 120
EARLIEST = pd.Timestamp("1800-01-01")


def detect(frame: Frame) -> list[Finding]:
    findings = []
    today = pd.Timestamp.now().normalize() + pd.Timedelta(days=1)
    for name, col in frame.columns.items():
        if col.type in NUMERIC_TYPES and col.numeric is not None:
            values = col.numeric
            reasons = pd.Series(False, index=values.index)
            if NON_NEGATIVE.search(name):
                reasons |= values < 0
            if AGE.search(name):
                reasons |= values > MAX_AGE
            if PERCENT.search(name):
                reasons |= (values < 0) | (values > 100)
            if reasons.any():
                findings.append(Finding(
                    "impossible_values", name, int(reasons.sum()),
                    "Quarantine these rows for review; don't guess a replacement.",
                    examples(col.raw[reasons].tolist()),
                ))
        elif col.type in ("date", "datetime") and col.dates is not None:
            bad = (col.dates > today) | (col.dates < EARLIEST)
            if bad.any():
                findings.append(Finding(
                    "impossible_values", name, int(bad.sum()),
                    "Quarantine dates in the future or before 1800 for review.",
                    examples(col.raw[bad].tolist()),
                ))
    return findings
