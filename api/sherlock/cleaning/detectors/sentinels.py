"""Sentinels: placeholder text (`N/A`, `null`, `?`, `-`, blank) and placeholder numbers (`-999`, `9999`).

A placeholder number counts only when it repeats and sits far outside the column's other values,
so a genuine 999 in a column of similar values is not flagged.
"""

import pandas as pd

from sherlock.cleaning.detectors.base import DetectorSpec, Finding, Frame, examples
from sherlock.profile.infer import NUMERIC_TYPES, SENTINEL_STRINGS

NUMERIC_SENTINELS = (-99999, -9999, -999, -99, 999, 9999, 99999)
FENCE = 3.0


def _numeric_sentinels(values: pd.Series) -> pd.Series:
    numbers = pd.to_numeric(values, errors="coerce")
    candidates = numbers.isin(NUMERIC_SENTINELS)
    if not candidates.any():
        return candidates
    rest = numbers[~candidates].dropna()
    if len(rest) < 10:
        return candidates & False
    q1, q3 = rest.quantile(0.25), rest.quantile(0.75)
    iqr = max(q3 - q1, 1e-9)
    outside = (numbers < q1 - FENCE * iqr) | (numbers > q3 + FENCE * iqr)
    flagged = candidates & outside
    counts = numbers[flagged].value_counts()
    repeated = numbers.isin(counts[counts >= 2].index)
    return flagged & repeated


def detect(frame: Frame) -> list[Finding]:
    findings = []
    for name, col in frame.columns.items():
        raw = col.raw.dropna().astype(str)
        if raw.empty:
            continue
        textual = raw.str.strip().str.lower().isin(SENTINEL_STRINGS)
        numeric = _numeric_sentinels(raw.str.strip()) if col.type in NUMERIC_TYPES or col.type == "text" else textual & False
        mask = textual | numeric
        if mask.any():
            findings.append(Finding(
                "sentinels", name, int(mask.sum()),
                "Treat these placeholders as missing values.",
                examples(raw[mask].tolist()),
            ))
    return findings


# A placeholder age of -999 becomes missing before the domain rule would quarantine its row.
SPEC = DetectorSpec(
    "sentinels", "placeholder values", "Placeholder text or numbers that stand for a missing value.",
    group="missing", weight=0.7, default_level="skews", scope="column", detect=detect,
    type_fix=True, runs_before=("impossible_values",),
)
