"""Mixed types: a mostly-numeric (or mostly-date) column with a minority of values that are neither.

Formatted numbers ("$1,200") are left to `numbers_as_text`; sentinels to `sentinels`.
"""

import pandas as pd

from sherlock.cleaning.detectors.base import Finding, Frame, examples
from sherlock.cleaning.detectors.numbers_as_text import clean_number
from sherlock.profile.infer import THRESHOLD, parse_dates

MAJORITY = 0.5
CODE_SHARE = 0.5


def detect(frame: Frame) -> list[Finding]:
    findings = []
    for name, col in frame.columns.items():
        text = col.text
        if text.empty or col.type in ("empty", "bool"):
            continue
        numeric = pd.to_numeric(text, errors="coerce").notna() | text.map(clean_number).notna()
        share = numeric.mean()
        if MAJORITY <= share < THRESHOLD:
            odd = text[~numeric]
            if odd.str.contains(r"\d", regex=True).mean() >= CODE_SHARE:
                continue  # mostly alphanumeric codes ("PC 17609"): a code column, not broken numbers
            findings.append(Finding(
                "mixed_types", name, len(odd),
                "Convert the values that spell out a number; quarantine the rest for review.",
                examples(odd.tolist()), {"expected": "number"},
            ))
            continue
        if share < MAJORITY and col.type not in ("id",):
            dates, _, date_share = parse_dates(text)
            if MAJORITY <= date_share < THRESHOLD:
                odd = text[dates.isna()]
                findings.append(Finding(
                    "mixed_types", name, len(odd),
                    "Parse the dates that use another format; quarantine the rest for review.",
                    examples(odd.tolist()), {"expected": "date"},
                ))
    return findings
