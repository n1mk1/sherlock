"""Numbers stored as text: currency symbols, thousands separators, locale decimals, %, (negatives)."""

import re

import pandas as pd

from sherlock.cleaning.detectors.base import DetectorSpec, Finding, Frame, Injector, examples
from sherlock.cleaning.detectors.fixtures import clean_frame
from sherlock.llm.schemas import Candidate
from sherlock.profile.infer import NUMERIC_TYPES, THRESHOLD

CURRENCY = re.compile(r"[$€£¥₹₩₽¢]|\b(USD|EUR|GBP|JPY|INR|PKR|CHF|CAD|AUD)\b", re.I)
THOUSANDS_COMMA = re.compile(r"^[+-]?\d{1,3}(,\d{3})+(\.\d+)?$")
THOUSANDS_DOT = re.compile(r"^[+-]?\d{1,3}(\.\d{3})+(,\d+)?$")
COMMA_DECIMAL = re.compile(r"^[+-]?\d+,\d+$")
THOUSANDS_SPACE = re.compile(r"^[+-]?\d{1,3}( \d{3})+([.,]\d+)?$")
MIN_SHARE = 0.5
# One separator then exactly three digits ("1,250", "2.500"): a thousands separator or a decimal one.
TWO_WAYS = re.compile(r"^[+-]?\d{1,3}[.,]\d{3}$")
NOT_A_NUMBER = re.compile(r"[^\W\d_aefinty]", re.I)  # a letter `float` never reads


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


def numeric_values(text: pd.Series) -> tuple[set, set]:
    """The distinct values that are plain numbers, and those that are formatted numbers, each value
    read once. A value with a letter left once currency codes are gone, other than those `float` reads
    ("1e5", "inf", "nan"), never reads ("R1001"), so it isn't parsed."""
    distinct = pd.Series(text.unique(), dtype=object)
    plain = pd.to_numeric(distinct, errors="coerce").notna()
    rest = distinct[~plain]
    maybe = rest[~rest.str.replace(CURRENCY, "", regex=True).str.contains(NOT_A_NUMBER)]
    return set(distinct[plain]), {v for v in maybe if pd.notna(clean_number(v))}  # "nan" reads as NaN: not one


def reads_one_way(values: pd.Series) -> bool:
    """No value reads as two numbers: none is digits, one separator, then exactly three digits once its
    currency, percent and spaces are gone ("1,250" is 1250 or 1.25)."""
    text = values.dropna().astype(str).str.replace(CURRENCY, "", regex=True).str.replace(r"[%\s]", "", regex=True)
    return not text.str.match(TWO_WAYS).any()


def needs_cleaning(text: pd.Series) -> pd.Series:
    """Values that aren't plain numbers but are formatted numbers."""
    return text.isin(numeric_values(text)[1])


def detect(frame: Frame) -> list[Finding]:
    findings = []
    for name, col in frame.columns.items():
        if col.type in NUMERIC_TYPES or col.type in ("empty", "date", "datetime", "bool") or col.text.empty:
            continue
        plain, formatted_values = numeric_values(col.text)
        plain_share = col.text.isin(plain).mean()
        formatted = col.text.isin(formatted_values)
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


def money(value) -> str:
    """A number written as money that keeps every digit ("$1,234.5"), so the clean value is recoverable."""
    return f"${float(value):,}".replace(".0", "") if float(value).is_integer() else f"${float(value):,}"


def damage(df, column: str, rows: list[int], rng) -> dict:
    return {(i, column): money(df.at[i, column]) for i in rows}


SPEC = DetectorSpec(
    "numbers_as_text", "numbers stored as text",
    "Numbers written with currency symbols, separators, locale decimals or percent signs.",
    group="types", weight=0.6, default_level="skews", scope="column", detect=detect,
    applies_to=frozenset(("category", "text", "id")),
    type_fix=True, code_fix=parse_candidate, code_fix_settles=reads_one_way,
    injectors={"money": Injector(damage)}, clean_fixture=lambda: (clean_frame(), "amount"),
)
