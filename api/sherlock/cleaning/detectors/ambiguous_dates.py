"""Ambiguous date formats: `03/04/2026` could be 3 April or 4 March.

A column is ambiguous when its day/month dates never show a part over 12, and mixed when some
values show day-first and others month-first.
"""

import re

import pandas as pd

from sherlock.cleaning.detectors.base import MAX_EXAMPLES, DetectorSpec, Finding, Frame, Injector, examples
from sherlock.cleaning.detectors.fixtures import with_column

DMY = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})(\s.*)?$")
MAJORITY = 0.5


def detect(frame: Frame) -> list[Finding]:
    findings = []
    for name, col in frame.columns.items():
        text = col.text
        if text.empty or col.type in ("int", "float", "bool", "empty"):
            continue
        parts = text.str.extract(DMY)
        matched = parts[0].notna()
        if matched.mean() < MAJORITY:
            continue
        first = parts[0][matched].astype(int)
        second = parts[1][matched].astype(int)
        day_first = first > 12
        month_first = second > 12
        if day_first.any() and month_first.any():
            minority = day_first if day_first.sum() < month_first.sum() else month_first
            findings.append(Finding(
                "ambiguous_dates", name, int(minority.sum()),
                "This column mixes day-first and month-first dates; pick one reading per value with review.",
                examples(text[matched][minority].tolist()), {"kind": "mixed"},
            ))
        elif not day_first.any() and not month_first.any():
            findings.append(Finding(
                "ambiguous_dates", name, int(matched.sum()),
                "Every date could be day-first or month-first; confirm the format before parsing.",
                examples(text[matched].tolist()), {"kind": "ambiguous"},
            ))
    return findings


def needs_order(issue: dict) -> bool:
    """A column every date of which reads both ways (kind `ambiguous`): no reading of the data settles
    the order, so the Cleaner doesn't guess one."""
    return (issue.get("details") or {}).get("kind") == "ambiguous"


def plan_extras(issue: dict) -> dict:
    """The plan item's date order (picked by the user, null until then), up to three of its values read
    both ways, and whether it is cleaned only with an order (TRD §4.4)."""
    from sherlock.cleaning.plan import both_ways

    pairs = both_ways(list(issue.get("examples") or [])[:MAX_EXAMPLES])
    return {"date_order": None, "both_ways": [{"value": v, "day_first": d, "month_first": m} for v, d, m in pairs],
            "needs_order": needs_order(issue)}


def written(fmt: str):
    """Damage that writes every chosen ISO date in one order (dd/mm/yyyy or mm/dd/yyyy)."""
    def damage(df, column: str, rows: list[int], rng) -> dict:
        return {(i, column): pd.Timestamp(df.at[i, column]).strftime(fmt) for i in rows}
    return damage


def clean_fixture():
    """Dates whose day is 12 or less and never equal to the month, so written either way each reads both ways."""
    days = [pd.Timestamp(2021, m, d) for m in range(1, 13) for d in range(1, 13) if d != m]
    return with_column("visit_date", [days[i % len(days)].date().isoformat() for i in range(200)]), "visit_date"


SPEC = DetectorSpec(
    "ambiguous_dates", "ambiguous dates", "Dates that could be read day-first or month-first.",
    group="types", weight=0.6, default_level="skews", scope="column", detect=detect,
    vote=True, plan_extras=plan_extras,
    injectors={"dmy_text": Injector(written("%d/%m/%Y"), share=1.0),
               "mdy_text": Injector(written("%m/%d/%Y"), share=1.0)},
    clean_fixture=clean_fixture,
)
