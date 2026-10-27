"""Mixed types: a mostly-numeric (or mostly-date) column with a minority of values that are neither.

Formatted numbers ("$1,200") are left to `numbers_as_text`; sentinels to `sentinels`.
"""

import pandas as pd

from sherlock.cleaning.detectors.base import DetectorSpec, Finding, Frame, Injector, examples
from sherlock.cleaning.detectors.fixtures import clean_frame
from sherlock.cleaning.detectors.numbers_as_text import numeric_values
from sherlock.profile.infer import THRESHOLD, parse_dates

MAJORITY = 0.5
CODE_SHARE = 0.5


def detect(frame: Frame) -> list[Finding]:
    findings = []
    for name, col in frame.columns.items():
        text = col.text
        if text.empty or col.type in ("empty", "bool"):
            continue
        plain, formatted = numeric_values(text)
        numeric = text.isin(plain | formatted)
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


NUMBER_WORDS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
                "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty")


def spell_numbers(df, column: str, rows: list[int], rng) -> dict:
    """Whole numbers spelled out ("7" becomes "seven"); a value that isn't one stays."""
    out = {}
    for i in rows:
        try:
            value = float(df.at[i, column])
        except (TypeError, ValueError):
            continue
        if value.is_integer() and 0 <= value < len(NUMBER_WORDS):
            out[(i, column)] = NUMBER_WORDS[int(value)]
    return out


def day_first_dates(df, column: str, rows: list[int], rng) -> dict:
    """ISO dates written day-first (31/01/2021), only where the day is over 12, so each reads one way."""
    out = {}
    for i in rows:
        d = pd.Timestamp(df.at[i, column])
        if d.day > 12:
            out[(i, column)] = d.strftime("%d/%m/%Y")
    return out


SPEC = DetectorSpec(
    "mixed_types", "values of another type",
    "A mostly numeric or mostly date column with a minority of values that are neither.",
    group="types", weight=0.9, default_level="skews", scope="column", detect=detect,
    applies_to=frozenset(("category", "text", "id")),
    injectors={"spelled": Injector(spell_numbers), "dmy_date": Injector(day_first_dates)},
    clean_fixture=lambda: (clean_frame(), "units"),
)
