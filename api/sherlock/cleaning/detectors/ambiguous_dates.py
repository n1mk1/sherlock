"""Ambiguous date formats: `03/04/2026` could be 3 April or 4 March.

A column is ambiguous when its day/month dates never show a part over 12, and mixed when some
values show day-first and others month-first.
"""

import re

from sherlock.cleaning.detectors.base import Finding, Frame, examples

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
