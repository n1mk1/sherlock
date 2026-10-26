"""Impossible values: negatives in quantities that can't be negative, ages over 120, percentages
outside 0–100, and dates in the future or before 1800. Quantities are recognised by column name.

`details` carries the column's domain rule and its plain words (`rule`): `low`/`high` for numbers;
`earliest`, and `after`, the first instant too late, for dates. The Cleaner builds the rule's own
quarantine from it (`loop.rule_candidate`, TRD §7.2).
"""

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


def bounds(name: str) -> tuple[float | None, float | None]:
    """The plausible domain the column's name gives it: (lowest, highest), None for no bound."""
    low = 0 if NON_NEGATIVE.search(name) or PERCENT.search(name) else None
    high = 100 if PERCENT.search(name) else MAX_AGE if AGE.search(name) else None
    return low, high


def rule_words(low, high) -> str:
    if low is not None and high is not None:
        return f"between {low:g} and {high:g}"
    return f"at least {low:g}" if low is not None else f"at most {high:g}"


def detect(frame: Frame) -> list[Finding]:
    findings = []
    after = pd.Timestamp.now().normalize() + pd.Timedelta(days=1)  # later than today
    for name, col in frame.columns.items():
        if col.type in NUMERIC_TYPES and col.numeric is not None:
            values = col.numeric
            low, high = bounds(name)
            if low is None and high is None:
                continue
            reasons = pd.Series(False, index=values.index)
            if low is not None:
                reasons |= values < low
            if high is not None:
                reasons |= values > high
            if reasons.any():
                findings.append(Finding(
                    "impossible_values", name, int(reasons.sum()),
                    "Quarantine these rows for review; don't guess a replacement.",
                    examples(col.raw[reasons].tolist()),
                    {"rule": f"{name} must be {rule_words(low, high)}", "low": low, "high": high},
                ))
        elif col.type in ("date", "datetime") and col.dates is not None:
            bad = (col.dates > after) | (col.dates < EARLIEST)
            if bad.any():
                findings.append(Finding(
                    "impossible_values", name, int(bad.sum()),
                    "Quarantine dates in the future or before 1800 for review.",
                    examples(col.raw[bad].tolist()),
                    {"rule": f"{name} must be between 1800 and today", "earliest": EARLIEST.date().isoformat(),
                     "after": after.date().isoformat()},
                ))
    return findings
