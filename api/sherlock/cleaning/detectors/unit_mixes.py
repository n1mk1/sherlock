"""Unit mixes: one column holding numbers with different units ("5 kg", "11 lb", "300 g")."""

import re

from sherlock.cleaning.detectors.base import Finding, Frame, examples

WITH_UNIT = re.compile(r"^\s*[-+]?\d+(?:[.,]\d+)?\s*([A-Za-z°µ%]+[A-Za-z0-9²³/]*)\s*$")
MAJORITY = 0.5


def detect(frame: Frame) -> list[Finding]:
    findings = []
    for name, col in frame.columns.items():
        if col.type not in ("category", "text") or col.text.empty:
            continue
        units = col.text.str.extract(WITH_UNIT)[0].str.lower()
        if units.notna().mean() < MAJORITY:
            continue
        counts = units.value_counts()
        if len(counts) < 2:
            continue
        mask = units.isin(counts.index[1:])
        findings.append(Finding(
            "unit_mixes", name, int(mask.sum()),
            f"Convert every value to one unit ({counts.index[0]}) and record the conversion.",
            examples(col.text[mask].tolist()), {"units": {u: int(n) for u, n in counts.items()}},
        ))
    return findings
