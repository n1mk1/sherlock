"""Cross-column violations: pairs like start/end or min/max where the later value is smaller.

Pairs are found by column name (start→end, begin→end, from→to, min→max, open→close,
created→updated, birth→death, departure→arrival, check_in→check_out), for numbers or dates.
"""

import re

from sherlock.cleaning.detectors.base import Finding, Frame, examples
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
