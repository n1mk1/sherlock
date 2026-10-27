"""Cross-column violations: pairs like start/end or min/max where the later value is smaller.

Pairs are found by column name (start→end, begin→end, from→to, min→max, open→close,
created→updated, birth→death, departure→arrival, check_in→check_out), for numbers or dates.
"""

import re

import pandas as pd

from sherlock.cleaning.detectors.base import DetectorSpec, Finding, Frame, Injector
from sherlock.cleaning.detectors.fixtures import clean_frame
from sherlock.profile.infer import NUMERIC_TYPES

PAIRS = (("start", "end"), ("begin", "end"), ("from", "to"), ("min", "max"), ("open", "close"),
         ("created", "updated"), ("birth", "death"), ("departure", "arrival"), ("check_in", "check_out"))


def _values(col):
    if col.type in NUMERIC_TYPES:
        return col.numeric
    if col.type in ("date", "datetime"):
        return col.dates
    return None


def detect(frame: Frame) -> list[Finding]:
    findings = []
    names = {n.lower(): n for n in frame.columns}
    for lower, name in names.items():
        for early, late in PAIRS:
            pattern = re.compile(rf"(^|[_\s]){early}($|[_\s])")
            if not pattern.search(lower):
                continue
            partner = names.get(pattern.sub(lambda m: f"{m.group(1)}{late}{m.group(2)}", lower))
            if partner is None:
                continue
            a, b = _values(frame.columns[name]), _values(frame.columns[partner])
            if a is None or b is None:
                continue
            bad = (b < a) & a.notna() & b.notna()
            if bad.any():
                findings.append(Finding(
                    "cross_column", partner, int(bad.sum()),
                    f"Quarantine rows where {partner} is before {name} for review.",
                    [int(i) for i in bad[bad].index[:5]], {"earlier": name, "later": partner},
                ))
    return findings


def earlier(columns, column: str) -> str | None:
    """The earlier column of the pair `column` ends ("end_date" → "start_date"), or None."""
    names = {n.lower(): n for n in columns}
    for early, late in PAIRS:
        pattern = re.compile(rf"(^|[_\s]){late}($|[_\s])")
        if pattern.search(column.lower()):
            found = names.get(pattern.sub(lambda m: f"{m.group(1)}{early}{m.group(2)}", column.lower()))
            if found:
                return found
    return None


def damage(df, column: str, rows: list[int], rng) -> dict:
    """Each chosen later value moved to before its earlier one: one less, or a day earlier."""
    partner = earlier(df.columns, column)
    out = {}
    for i in rows if partner else []:
        a = df.at[i, partner]
        try:
            out[(i, column)] = f"{float(a) - 1:g}"
        except (TypeError, ValueError):
            out[(i, column)] = (pd.Timestamp(a) - pd.Timedelta(days=1)).date().isoformat()
    return out


SPEC = DetectorSpec(
    "cross_column", "values out of order", "Rows where a later value, such as an end, is before its earlier one.",
    group="records", weight=0.6, default_level="skews", scope="columns", detect=detect,
    injectors={"order": Injector(damage)}, clean_fixture=lambda: (clean_frame(), "end_date"),
)
