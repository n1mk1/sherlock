"""Type and role inference from values (PRD PROF-1, TRD §6.1). Code, not LLM.

Types are inferred from the text of each value, because version 1 is imported all-VARCHAR.
A type wins when at least 99% of the non-missing values parse as it.
"""

import re
import warnings
from dataclasses import dataclass, field

import pandas as pd

THRESHOLD = 0.99
SENTINEL_STRINGS = frozenset({
    "", "n/a", "na", "null", "none", "nan", "?", "-", "--", "#n/a", "missing", "undefined", "nil",
})
BOOL_WORDS = frozenset({"true", "false", "yes", "no", "t", "f", "y", "n"})
INT_RE = re.compile(r"[+-]?\d+")
DATE_FORMATS = (
    "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y", "%Y/%m/%d", "%d-%m-%Y", "%m-%d-%Y",
    "%d %b %Y", "%d-%b-%Y", "%b %d, %Y", "%d %B %Y", "%B %d, %Y", "%d/%m/%y", "%m/%d/%y",
)
ID_NAME = re.compile(r"(^id$|_id$|^id_|uuid|guid|(^|_)key$|(^|_)code$|(^|_)number$|^no$|_no$|^num$)", re.I)
TARGET_NAMES = frozenset({"target", "label", "outcome", "survived", "churn", "converted", "default", "y"})
NUMERIC_TYPES = frozenset({"int", "float"})


@dataclass
class Column:
    name: str
    raw: pd.Series                  # the values as stored (strings for version 1), NULL as None
    text: pd.Series                 # non-null values as stripped strings, sentinel strings removed
    type: str = "text"
    role: str = "dimension"
    numeric: pd.Series | None = None  # parsed numbers aligned to `raw` (NaN where not a number)
    dates: pd.Series | None = None    # parsed datetimes aligned to `raw`
    date_format: str | None = None
    distinct: int = 0
    flags: list[str] = field(default_factory=list)

    @property
    def missing(self) -> int:
        return int(self.raw.isna().sum())

    @property
    def nonnull(self) -> int:
        return int(self.raw.notna().sum())


def as_text(series: pd.Series) -> pd.Series:
    """Non-null values as stripped strings, without sentinel strings, keeping the index."""
    s = series.dropna().astype(str).str.strip()
    return s[~s.str.lower().isin(SENTINEL_STRINGS)]


def _to_datetime(text: pd.Series, fmt: str) -> pd.Series:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)  # pandas will raise on mixed offsets one day
        try:
            parsed = pd.to_datetime(text, format=fmt, errors="coerce")
        except (TypeError, ValueError):
            parsed = None
    if not pd.api.types.is_datetime64_any_dtype(parsed):  # mixed UTC offsets come back as objects: not dates
        return pd.Series(pd.NaT, index=text.index, dtype="datetime64[ns]")
    return parsed


def parse_dates(text: pd.Series) -> tuple[pd.Series, str | None, float]:
    """Best date parse: ISO 8601 first, then the format set. Returns (parsed, format, share)."""
    if text.empty:
        return pd.Series(dtype="datetime64[ns]"), None, 0.0
    best = (_to_datetime(text, "ISO8601"), "ISO8601")
    best_share = best[0].notna().mean()
    if best_share < THRESHOLD:
        for fmt in DATE_FORMATS:
            parsed = _to_datetime(text, fmt)
            share = parsed.notna().mean()
            if share > best_share:
                best, best_share = (parsed, fmt), share
            if share >= THRESHOLD:
                break
    return best[0], best[1], float(best_share)


def infer_type(col: Column, db_type: str | None = None) -> None:
    """Set `col.type` (int | float | bool | date | datetime | category | text | id | empty) and parses."""
    text = col.text
    col.distinct = int(col.raw.dropna().astype(str).nunique())
    if db_type and db_type not in ("VARCHAR", "TEXT"):
        col.type = _from_db_type(db_type)
    if text.empty:
        col.type = "empty"
        col.flags.append("empty")
        return
    numeric = pd.to_numeric(text, errors="coerce")
    if col.type in ("text",) or db_type in (None, "VARCHAR", "TEXT"):
        lower = text.str.lower()
        if lower.isin(BOOL_WORDS).mean() >= THRESHOLD:
            col.type = "bool"
        elif text.str.fullmatch(INT_RE).mean() >= THRESHOLD:
            col.type = "int"
        elif numeric.notna().mean() >= THRESHOLD:
            col.type = "float"
        else:
            dates, fmt, share = parse_dates(text)
            if share >= THRESHOLD:
                has_time = ((dates.dt.hour != 0) | (dates.dt.minute != 0) | (dates.dt.second != 0)).any()
                col.type = "datetime" if has_time else "date"
                col.dates, col.date_format = dates.reindex(col.raw.index), fmt
            else:
                col.type = _textual_type(col)
    if col.type in NUMERIC_TYPES:
        col.numeric = numeric.reindex(col.raw.index)
    elif col.type in ("date", "datetime") and col.dates is None:
        dates, fmt, _ = parse_dates(text)
        col.dates, col.date_format = dates.reindex(col.raw.index), fmt


def _from_db_type(db_type: str) -> str:
    t = db_type.upper()
    if t in ("BIGINT", "INTEGER", "SMALLINT", "TINYINT", "HUGEINT", "UBIGINT", "UINTEGER"):
        return "int"
    if t in ("DOUBLE", "FLOAT", "REAL") or t.startswith("DECIMAL"):
        return "float"
    if t == "BOOLEAN":
        return "bool"
    if t == "DATE":
        return "date"
    if t.startswith("TIMESTAMP"):
        return "datetime"
    return "text"


def _textual_type(col: Column) -> str:
    n = len(col.text)
    unique_ratio = col.text.nunique() / n
    if unique_ratio > 0.95 and n >= 20:
        return "id"
    if col.text.nunique() <= 50 or unique_ratio <= 0.05:
        return "category"
    return "text"


def infer_role(col: Column, is_last: bool) -> None:
    """TRD §6.1 role rules, first match wins."""
    n = len(col.text)
    if col.type == "empty":
        col.role = "empty"
        return
    distinct = col.text.nunique()
    unique_ratio = distinct / n if n else 0.0
    if unique_ratio > 0.95 and n >= 20 and (ID_NAME.search(col.name) or col.type in ("text", "id")):
        col.role = "id"
    elif col.type in ("date", "datetime"):
        col.role = "time"
    elif (distinct == 2 or distinct <= 10) and (col.name.strip().lower() in TARGET_NAMES or is_last):
        col.role = "target_like"
    elif col.type == "int" and distinct <= 12:
        col.role = "dimension"
    elif col.type in NUMERIC_TYPES:
        col.role = "measure"
    elif distinct <= 50 or unique_ratio <= 0.05:
        col.role = "dimension"
    elif col.text.str.len().mean() > 40:
        col.role = "free_text"
    else:
        col.role = "dimension"
