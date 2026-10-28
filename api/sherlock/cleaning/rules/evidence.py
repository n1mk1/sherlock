"""Is a suggested check backed by the web excerpt it cites? (docs/plans/tavily.md §3.3, Rule 2)

The model may say a check comes from an excerpt, but a number a user reads as sourced is never taken on
the model's word: `backed` finds every threshold in the excerpt's own text, by code. A range or date
window is backed when each bound it gives appears there as a token in one of its plain forms (`120`,
`120.0`, `1,000`; a date as ISO, as digits in another order, or with a month name). An allowed list is
backed when every value appears as a whole word, ignoring case. A kind with no number in it (a pattern,
not missing, unique, an order, a dependency) is backed when the excerpt names the column, or when the
column's own note was read from that excerpt.

The function is pure and knows no dataset: it reads the spec and the text. A check that fails stays a
plain suggestion (never refused); only the evidence is dropped.
"""

import re
from datetime import date

# A token ends where a word or a digit group goes on: "120" is not in "1200", "120.5" or "1,200".
_LEFT = r"(?<!\w)(?<!\w['’])(?<![\d][.,])"
_RIGHT = r"(?![\w])(?!['’]\w)(?![.,]\d)"
MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december")
_SEP = r"\s?[-/.]\s?"


def _token(pattern: str) -> re.Pattern:
    return re.compile(_LEFT + "(?:" + pattern + ")" + _RIGHT, re.I)


def _plain(excerpt: str) -> str:
    """The excerpt with a typographic minus written as a hyphen, so "−5" and "-5" are one token."""
    return excerpt.replace("−", "-").replace("–", "-")


def _number_forms(x: float) -> str:
    """The regex for one bound in its plain written forms."""
    if x == int(x) and abs(x) < 1e15:
        n = int(x)
        sign = "-" if n < 0 else ""
        digits = str(abs(n))
        forms = {digits, f"{abs(n):,}"}
        return sign + "(?:" + "|".join(re.escape(f) for f in sorted(forms, key=len, reverse=True)) + r")(?:\.0+)?"
    text = f"{x:f}".rstrip("0") if "e" in repr(x) else repr(x)
    return re.escape(text) + "0*"


def _number_in(x: float, excerpt: str) -> bool:
    return _token(_number_forms(x)).search(_plain(excerpt)) is not None


def _ordinal(n: int) -> str:
    return rf"0?{n}(?:st|nd|rd|th)?"


def _date_in(iso: str, excerpt: str) -> bool:
    """The date as written ISO, as its year, month and day in the usual orders, or with a month name.
    A year alone backs January 1 (an earliest date) or December 31 (a latest one)."""
    try:
        d = date.fromisoformat(iso)
    except (TypeError, ValueError):
        return False
    text = _plain(excerpt)
    y, m, day = d.year, d.month, d.day
    month = MONTHS[m - 1]
    names = rf"(?:{month}|{month[:3]}\.?" + (r"|sept\.?" if m == 9 else "") + ")"
    forms = [
        re.escape(iso),
        rf"{y}{_SEP}0?{m}{_SEP}0?{day}",                    # 2020-1-5, 2020/01/05, 2020.01.05
        rf"0?{day}{_SEP}0?{m}{_SEP}{y}",                    # 5/1/2020
        rf"0?{m}{_SEP}0?{day}{_SEP}{y}",                    # 1/5/2020
        rf"{_ordinal(day)}\s+(?:of\s+)?{names},?\s+{y}",    # 5 January 2020, 5th of Jan 2020
        rf"{names}\s+{_ordinal(day)},?\s+{y}",              # January 5, 2020
    ]
    if (m, day) in ((1, 1), (12, 31)):
        forms.append(str(y))
    return _token("|".join(forms)).search(text) is not None


def _word_in(value: str, excerpt: str) -> bool:
    value = " ".join(value.split())
    if not value:
        return False
    pattern = r"\s+".join(re.escape(w) for w in value.split())
    return _token(pattern).search(excerpt) is not None


def _name(text: str) -> str:
    """A column name as plain lowercase words: "Home_Planet" and "home planet" are one."""
    return " ".join(re.sub(r"[_\s]+", " ", text.casefold()).split())


def names(excerpt: str, column: str) -> bool:
    """The excerpt names the column, ignoring case and treating "_" as a space."""
    want = _name(column)
    return bool(want) and re.search(r"(?<!\w)" + re.escape(want) + r"(?!\w)", _name(excerpt)) is not None


def _same_quote(a: str, b: str) -> bool:
    a, b = _name(a), _name(b)
    return bool(a) and bool(b) and (a in b or b in a)


def backed(spec: dict, excerpt: str, column_note: str | None = None) -> bool:
    """True when the check `spec` ({kind, column, params, …}) is stated by `excerpt`, word for word.

    `column_note` is the quote the column's note was read from, when it has one: a check that names no
    number is backed by the excerpt if the column's note comes from that same excerpt."""
    if not isinstance(spec, dict) or not isinstance(excerpt, str) or not excerpt.strip():
        return False
    kind, params = spec.get("kind"), spec.get("params") or {}
    if kind == "range":
        bounds = [params.get(k) for k in ("min", "max") if params.get(k) is not None]
        try:
            return bool(bounds) and all(_number_in(float(b), excerpt) for b in bounds)
        except (TypeError, ValueError, OverflowError):
            return False
    if kind == "date_window":
        bounds = [params.get(k) for k in ("earliest", "latest") if params.get(k)]
        return bool(bounds) and all(_date_in(str(b), excerpt) for b in bounds)
    if kind == "allowed":
        values = params.get("values")
        return bool(values) and all(_word_in(str(v), excerpt) for v in values)
    if kind in ("pattern", "not_missing", "unique", "order", "depends"):
        column = str(spec.get("column") or "")
        return names(excerpt, column) or (column_note is not None and _same_quote(excerpt, column_note))
    return False
