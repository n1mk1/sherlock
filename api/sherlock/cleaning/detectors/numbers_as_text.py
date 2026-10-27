"""Numbers stored as text: currency symbols, thousands separators, locale decimals, %, (negatives)."""

import re

import pandas as pd

from sherlock.cleaning.detectors.base import DetectorSpec, Finding, Frame, examples
from sherlock.llm.schemas import Candidate
from sherlock.profile.infer import NUMERIC_TYPES, THRESHOLD

CURRENCY = re.compile(r"[$€£¥₹₩₽¢]|\b(USD|EUR|GBP|JPY|INR|PKR|CHF|CAD|AUD)\b", re.I)
THOUSANDS_COMMA = re.compile(r"^[+-]?\d{1,3}(,\d{3})+(\.\d+)?$")
THOUSANDS_DOT = re.compile(r"^[+-]?\d{1,3}(\.\d{3})+(,\d+)?$")
COMMA_DECIMAL = re.compile(r"^[+-]?\d+,\d+$")
THOUSANDS_SPACE = re.compile(r"^[+-]?\d{1,3}( \d{3})+([.,]\d+)?$")
MIN_SHARE = 0.5


def clean_number(value: str) -> float | None:
    """Parse a formatted number ("$1,234.50", "12,5", "1.234,56", "45%", "(300)"), or None."""
    s = CURRENCY.sub("", str(value)).strip().replace(" ", " ")
    if THOUSANDS_SPACE.match(s):
        s = s.replace(" ", "")  # "1 234 567" (a space only counts as a separator in groups of three)
    s = s.replace("'", "").strip()
    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1]
    if s.endswith("-") and s[:-1].replace(".", "").replace(",", "").isdigit():
        negative, s = True, s[:-1]
    s = s.rstrip("%")
    if THOUSANDS_COMMA.match(s):
        s = s.replace(",", "")
    elif THOUSANDS_DOT.match(s):
        s = s.replace(".", "").replace(",", ".")
    elif COMMA_DECIMAL.match(s):
        s = s.replace(",", ".")
    try:
        number = float(s)
    except ValueError:
        return None
    return -number if negative else number


def needs_cleaning(text: pd.Series) -> pd.Series:
    """Values that aren't plain numbers but are formatted numbers."""
    plain = pd.to_numeric(text, errors="coerce").notna()
    cleaned = text[~plain].map(clean_number).notna()
    return cleaned.reindex(text.index, fill_value=False)


def detect(frame: Frame) -> list[Finding]:
    findings = []
    for name, col in frame.columns.items():
        if col.type in NUMERIC_TYPES or col.type in ("empty", "date", "datetime", "bool") or col.text.empty:
            continue
        plain_share = pd.to_numeric(col.text, errors="coerce").notna().mean()
        formatted = needs_cleaning(col.text)
        if plain_share < THRESHOLD and plain_share + formatted.mean() >= MIN_SHARE and formatted.any():
            findings.append(Finding(
                "numbers_as_text", name, int(formatted.sum()),
                "Strip currency symbols, separators and % and read the column as numbers.",
                examples(col.text[formatted].tolist()),
            ))
    return findings


def parse_candidate(issue: dict) -> Candidate | None:
    """The code's own fix, built without the model (PRD CLEAN-4e): parse the column with
    `parse_numbers` and quarantine the values it can't read."""
    column = issue.get("column")
    if column is None:
        return None
    code = (f"parsed = parse_numbers(df[{column!r}])\nresult = df.copy()\nresult[{column!r}] = parsed\n"
            f"result = quarantine_rows(result, parse_failures(df[{column!r}], parsed), {'unparsed: ' + column!r})")
    return Candidate(label="Parse numbers", code=code,
                     expected_effect="Reads the column as numbers; values that aren't numbers are set aside.")


SPEC = DetectorSpec(
    "numbers_as_text", "numbers stored as text",
    "Numbers written with currency symbols, separators, locale decimals or percent signs.",
    group="types", weight=0.6, default_level="skews", scope="column", detect=detect,
    type_fix=True, code_fix=parse_candidate,
)
