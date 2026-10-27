"""Impossible values: negatives in quantities that can't be negative, ages over 120, percentages
outside 0–100, and dates in the future or before 1800. Quantities are recognised by column name.

`details` carries the column's domain rule and its plain words (`rule`): `low`/`high` for numbers;
`earliest`, and `after`, the first instant too late, for dates. The Cleaner builds the rule's own
quarantine from it (`rule_candidate`, the spec's `code_fix`, TRD §7.2).
"""

import re

import pandas as pd

from sherlock.cleaning.detectors.base import DetectorSpec, Finding, Frame, Injector, examples
from sherlock.cleaning.detectors.fixtures import clean_frame
from sherlock.llm.schemas import Candidate
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


RULE_LABEL = "Quarantine impossible values"


def rule_candidate(issue: dict) -> Candidate | None:
    """The domain rule's own fix: quarantine the rows it names, built by code from the detector's
    `details`, so a value outside the column's domain has a fix whatever the model proposes. None
    for a rule the details don't give."""
    column, d = issue.get("column"), issue.get("details") or {}
    if column is None:
        return None
    if d.get("earliest") and d.get("after"):
        load = f"values = pd.to_datetime(df[{column!r}], errors='coerce')"
        tests = [f"(values < pd.Timestamp({d['earliest']!r}))", f"(values > pd.Timestamp({d['after']!r}))"]
    else:
        load = f"values = pd.to_numeric(df[{column!r}], errors='coerce')"
        tests = [f"(values {op} {d[k]!r})" for k, op in (("low", "<"), ("high", ">")) if d.get(k) is not None]
    if not tests:
        return None
    code = f"{load}\nbad = {' | '.join(tests)}\nresult = quarantine_rows(df, bad, {'impossible: ' + column!r})"
    return Candidate(label=RULE_LABEL, code=code,
                     expected_effect="Sets aside the rows whose value breaks the column's domain rule.")


def damage(df, column: str, rows: list[int], rng) -> dict:
    """Each chosen number made negative, for a column whose name says it can't be."""
    out = {}
    for i in rows:
        try:
            out[(i, column)] = f"-{abs(float(df.at[i, column])) + 1:g}"
        except (TypeError, ValueError):
            continue
    return out


SPEC = DetectorSpec(
    "impossible_values", "impossible values",
    "Values outside the plausible domain the column's name gives it, such as a negative quantity or a future date.",
    group="records", weight=0.7, default_level="skews", scope="column", detect=detect,
    domain_rule=True, code_fix=rule_candidate,
    injectors={"negative": Injector(damage)}, clean_fixture=lambda: (clean_frame(), "units"),
)
