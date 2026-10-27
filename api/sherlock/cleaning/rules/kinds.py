"""The rule kinds (PRD CLEAN-13, TRD §7.1 step 4): constraints a fixed interpreter runs, so a check you
write, a rule pack or a suggestion is data, never code.

Each kind has the column types it applies to, its default level, a parameter check (run when a rule is
saved), a vectorised `mask` over a detector `Frame` (True on a row that breaks the rule; pandas
operations, never `eval`, `query` or per-row Python, but the timed pattern match), the pandas `code` of
the same mask for the Cleaner's quarantine (run in the sandbox), and the rule in plain words.
"""

import re
from dataclasses import dataclass
from typing import Callable

import pandas as pd

MAX_VALUES = 200
MAX_PATTERN = 200
NUMBERS = ("int", "float")
DATES = ("date", "datetime")


class RuleError(ValueError):
    """A rule that can't be saved: `field` names what is wrong."""

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field


@dataclass(frozen=True)
class Kind:
    types: tuple[str, ...]          # the column types it applies to; empty = any
    default_level: str
    check: Callable[[dict, dict], dict]          # (params, columns {name: type}) → normalized params
    mask: Callable[[object, str, dict], pd.Series]   # (frame, column, params) → bad rows
    code: Callable[[str, dict], str]             # (column, params) → pandas code that sets `bad`
    words: Callable[[str, dict], str]            # (column, params) → "fare is at least 0"


def _num(params: dict, key: str) -> float | None:
    v = params.get(key)
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        raise RuleError(f"params.{key}", f"{key} must be a number.") from None


def _date(params: dict, key: str) -> str | None:
    v = params.get(key)
    if v is None or v == "":
        return None
    try:
        return pd.Timestamp(v).date().isoformat()
    except (TypeError, ValueError):
        raise RuleError(f"params.{key}", f"{key} must be a date (YYYY-MM-DD).") from None


def _other(params: dict, key: str, columns: dict, types: tuple[str, ...] = ()) -> str:
    other = params.get(key)
    if other not in columns:
        raise RuleError(f"params.{key}", f"{key} must be a column of this file.")
    if types and columns[other] not in types:
        raise RuleError(f"params.{key}", f"{other} is {columns[other]}; this check needs {' or '.join(types)}.")
    return other


def _g(x: float) -> str:
    return f"{x:g}"


# --- range ------------------------------------------------------------------------------------

def _range_check(p, columns):
    low, high = _num(p, "min"), _num(p, "max")
    if low is None and high is None:
        raise RuleError("params", "Give a lowest value, a highest value, or both.")
    if low is not None and high is not None and low > high:
        raise RuleError("params.min", "The lowest value is above the highest.")
    return {"min": low, "max": high}


def _range_mask(frame, column, p):
    values = frame.columns[column].numeric
    bad = pd.Series(False, index=values.index)
    if p["min"] is not None:
        bad |= values < p["min"]
    if p["max"] is not None:
        bad |= values > p["max"]
    return bad.fillna(False)


def _range_code(column, p):
    tests = [f"(values < {p['min']!r})"] if p["min"] is not None else []
    tests += [f"(values > {p['max']!r})"] if p["max"] is not None else []
    return f"values = pd.to_numeric(df[{column!r}], errors='coerce')\nbad = {' | '.join(tests)}"


def _range_words(column, p):
    if p["min"] is not None and p["max"] is not None:
        return f"{column} is between {_g(p['min'])} and {_g(p['max'])}"
    return f"{column} is at least {_g(p['min'])}" if p["min"] is not None else f"{column} is at most {_g(p['max'])}"


# --- date_window ------------------------------------------------------------------------------

def _window_check(p, columns):
    earliest, latest = _date(p, "earliest"), _date(p, "latest")
    if earliest is None and latest is None:
        raise RuleError("params", "Give an earliest date, a latest date, or both.")
    if earliest and latest and earliest > latest:
        raise RuleError("params.earliest", "The earliest date is after the latest.")
    return {"earliest": earliest, "latest": latest}


def _window_mask(frame, column, p):
    dates = frame.columns[column].dates
    bad = pd.Series(False, index=dates.index)
    if p["earliest"]:
        bad |= dates < pd.Timestamp(p["earliest"])
    if p["latest"]:
        bad |= dates >= pd.Timestamp(p["latest"]) + pd.Timedelta(days=1)
    return bad.fillna(False)


def _window_code(column, p):
    tests = [f"(values < pd.Timestamp({p['earliest']!r}))"] if p["earliest"] else []
    tests += [f"(values >= pd.Timestamp({p['latest']!r}) + pd.Timedelta(days=1))"] if p["latest"] else []
    return f"values = pd.to_datetime(df[{column!r}], errors='coerce')\nbad = {' | '.join(tests)}"


def _window_words(column, p):
    if p["earliest"] and p["latest"]:
        return f"{column} is between {p['earliest']} and {p['latest']}"
    return f"{column} is on or after {p['earliest']}" if p["earliest"] else f"{column} is on or before {p['latest']}"


# --- allowed ----------------------------------------------------------------------------------

def _norm(s: pd.Series) -> pd.Series:
    return s.astype("string").str.strip().str.casefold()


def _allowed_check(p, columns):
    values = p.get("values")
    if not isinstance(values, list) or not values or len(values) > MAX_VALUES:
        raise RuleError("params.values", f"Give between 1 and {MAX_VALUES} allowed values.")
    return {"values": [str(v).strip() for v in values if str(v).strip()]}


def _allowed_mask(frame, column, p):
    raw = frame.columns[column].raw
    allowed = {v.casefold() for v in p["values"]}
    return (raw.notna() & ~_norm(raw).isin(allowed)).fillna(False).astype(bool)


def _allowed_code(column, p):
    allowed = sorted({v.casefold() for v in p["values"]})
    return (f"text = df[{column!r}].astype('string').str.strip().str.casefold()\n"
            f"bad = df[{column!r}].notna() & ~text.isin({allowed!r})")


def _allowed_words(column, p):
    shown = ", ".join(p["values"][:5]) + (", …" if len(p["values"]) > 5 else "")
    return f"{column} is one of {shown}"


# --- pattern ----------------------------------------------------------------------------------

BACKREF = re.compile(r"\\[1-9]|\(\?P=|\\k<")
NESTED = re.compile(r"\((?:[^()\\]|\\.)*[*+}](?:[^()\\]|\\.)*\)[*+{?]")


def _pattern_check(p, columns):
    pattern = p.get("regex")
    if not isinstance(pattern, str) or not pattern or len(pattern) > MAX_PATTERN:
        raise RuleError("params.regex", f"Give a pattern of at most {MAX_PATTERN} characters.")
    if not (pattern.startswith("^") and pattern.endswith("$")):
        raise RuleError("params.regex", "The pattern must be anchored: start with ^ and end with $.")
    if BACKREF.search(pattern):
        raise RuleError("params.regex", "The pattern can't use back-references.")
    if NESTED.search(pattern):
        raise RuleError("params.regex", "The pattern can't repeat a group that repeats (it could run for ever).")
    try:
        re.compile(pattern)
    except re.error as exc:
        raise RuleError("params.regex", f"The pattern doesn't read: {exc}.") from None
    return {"regex": pattern}


def _pattern_mask(frame, column, p, deadline: float | None = None):
    import time

    import regex

    raw = frame.columns[column].raw
    compiled = regex.compile(p["regex"])
    text = raw.dropna().astype(str)
    fails = set()
    for value in text.unique():  # each distinct value once, with a match timeout
        left = None if deadline is None else max(deadline - time.monotonic(), 0.0)
        if left == 0.0:
            raise TimeoutError
        if compiled.fullmatch(value, timeout=left) is None:
            fails.add(value)
    return raw.notna() & raw.astype(str).isin(fails)


def _pattern_code(column, p):
    return (f"text = df[{column!r}].astype('string')\n"
            f"bad = df[{column!r}].notna() & ~text.str.fullmatch({p['regex']!r}, na=False)")


def _pattern_words(column, p):
    return f"{column} matches the pattern {p['regex']}"


# --- not_missing, unique ------------------------------------------------------------------------

def _none_check(p, columns):
    return {}


def _missing_mask(frame, column, p):
    return frame.columns[column].raw.isna()


def _missing_code(column, p):
    return f"bad = df[{column!r}].isna()"


def _unique_mask(frame, column, p):
    raw = frame.columns[column].raw
    return (raw.notna() & raw.astype(str).duplicated(keep="first")).astype(bool)


def _unique_code(column, p):
    return f"bad = df[{column!r}].notna() & df[{column!r}].astype(str).duplicated(keep='first')"


# --- order ------------------------------------------------------------------------------------

def _order_check(p, columns):
    op = p.get("op", "<")
    if op not in ("<", "<="):
        raise RuleError("params.op", "The order is < or <=.")
    left = _other(p, "left", columns, NUMBERS + DATES)
    return {"left": left, "op": op, "as": "number" if columns[left] in NUMBERS else "date"}


def _values(col):
    return col.numeric if col.numeric is not None else col.dates


def _order_mask(frame, column, p):
    left, right = _values(frame.columns[p["left"]]), _values(frame.columns[column])
    if left is None or right is None:
        return pd.Series(False, index=frame.df.index)
    ok = left < right if p["op"] == "<" else left <= right
    return (left.notna() & right.notna() & ~ok).fillna(False).astype(bool)


def _order_code(column, p):
    load = "pd.to_numeric" if p["as"] == "number" else "pd.to_datetime"
    return (f"left = {load}(df[{p['left']!r}], errors='coerce')\nright = {load}(df[{column!r}], errors='coerce')\n"
            f"bad = left.notna() & right.notna() & ~(left {p['op']} right)")


def _order_words(column, p):
    return f"{p['left']} is {'before' if p['op'] == '<' else 'at most'} {column}"


# --- depends ----------------------------------------------------------------------------------

def _depends_check(p, columns):
    return {"from": _other(p, "from", columns)}


def _depends_mask(frame, column, p):
    pair = frame.df[[p["from"], column]].dropna().astype(str)
    if pair.empty:
        return pd.Series(False, index=frame.df.index)
    modes = pair.groupby(p["from"])[column].agg(lambda s: s.value_counts().index[0])
    bad = pair[column] != pair[p["from"]].map(modes)
    return bad.reindex(frame.df.index, fill_value=False).astype(bool)


def _depends_code(column, p):
    f = p["from"]
    return (f"pair = df[[{f!r}, {column!r}]].dropna().astype(str)\n"
            f"modes = pair.groupby({f!r})[{column!r}].agg(lambda s: s.value_counts().index[0])\n"
            f"bad = (pair[{column!r}] != pair[{f!r}].map(modes)).reindex(df.index, fill_value=False)")


def _depends_words(column, p):
    return f"each {p['from']} has one {column}"


KINDS: dict[str, Kind] = {
    "range": Kind(NUMBERS, "skews", _range_check, _range_mask, _range_code, _range_words),
    "date_window": Kind(DATES, "skews", _window_check, _window_mask, _window_code, _window_words),
    "allowed": Kind(("category", "text", "bool", "id", "int"), "splits", _allowed_check, _allowed_mask, _allowed_code,
                    _allowed_words),
    "pattern": Kind(("category", "text", "id"), "splits", _pattern_check, _pattern_mask, _pattern_code, _pattern_words),
    "not_missing": Kind((), "check", _none_check, _missing_mask, _missing_code,
                        lambda c, p: f"{c} is filled in"),
    "unique": Kind((), "skews", _none_check, _unique_mask, _unique_code, lambda c, p: f"{c} is unique"),
    "order": Kind(NUMBERS + DATES, "skews", _order_check, _order_mask, _order_code, _order_words),
    "depends": Kind((), "check", _depends_check, _depends_mask, _depends_code, _depends_words),
}
ACTIONS = ("quarantine", "flag", "fix")


def from_draft(draft: dict) -> dict:
    """A rule from the model's plain fields (`RuleDraft`): the parameters its kind takes."""
    kind = draft.get("kind")
    params = {"range": {"min": draft.get("min"), "max": draft.get("max")},
              "date_window": {"earliest": draft.get("earliest"), "latest": draft.get("latest")},
              "allowed": {"values": draft.get("values")}, "pattern": {"regex": draft.get("regex")},
              "order": {"left": draft.get("other"), "op": "<"}, "depends": {"from": draft.get("other")}}.get(kind, {})
    return {"kind": kind, "column": draft.get("column"), "params": params, "action": draft.get("action")}
