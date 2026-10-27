"""Vetted pandas helpers the Cleaner's code composes (TRD §7.2). They run inside the sandbox, where
they are in scope by name, and are vendored into exported notebooks (the ones a step uses).

Rules every helper keeps:
- Inputs are never changed in place; each returns a new Series or DataFrame.
- Nothing removes rows. Rows that should go are quarantined with `quarantine_rows`.
- A parse never hides a failure: `parse_failures(original, parsed)` gives the rows that didn't
  parse, and the caller quarantines them.
- A merge never joins categories that are different on purpose (`_merge_refusal`): values
  that differ only in their numbers ("Region 1", "Region 2"), or two values that are both common,
  unless one is the other with an inner letter left out ("Wst", "West": a typo, `_dropped_letter`).
"""

import re

import numpy as np
import pandas as pd

SENTINELS = frozenset({
    "", "n/a", "na", "null", "none", "nan", "?", "-", "--", "#n/a", "missing", "undefined", "nil",
})
_CURRENCY = re.compile(r"[$€£¥₹]|\b(?:usd|eur|gbp|jpy|inr|cad|aud|chf)\b", re.I)
_SPACES = re.compile(r"\s+")
_DATE_FORMATS = {
    "dmy": ("%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%d %b %Y", "%d %B %Y", "%d-%b-%Y"),
    "mdy": ("%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%b %d, %Y", "%B %d, %Y", "%b %d %Y"),
    "ymd": ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d"),
}

_COMMON_SHARE = 0.05  # a value on 5% of the rows or more (and more than one row) is a category of its own
_NUMBERS = re.compile(r"\d+")

__all__ = [
    "strip_sentinels", "parse_numbers", "parse_dates_smart", "normalize_whitespace_case",
    "canonicalize_categories", "extract_pattern", "fill_by_group", "flag_rows", "quarantine_rows",
    "fix_encoding", "parse_failures", "keep_outside_scope",
]


def _text(s: pd.Series) -> pd.Series:
    """Values as stripped strings, missing stays missing."""
    return s.where(s.isna(), s.astype(str).str.strip())


def strip_sentinels(s: pd.Series, extra=()) -> pd.Series:
    """Placeholder values (`N/A`, `null`, `?`, `-`, blank, plus `extra`, e.g. `[-999]`) become missing."""
    lowered = _text(s).str.lower() if s.dtype == object else None
    mask = lowered.isin(SENTINELS) if lowered is not None else pd.Series(False, index=s.index)
    if extra:
        extra_text = {str(e).strip().lower() for e in extra}
        as_text = s.astype(str).str.strip().str.lower()
        numeric = pd.to_numeric(s, errors="coerce")
        extra_numbers = [float(e) for e in extra if _is_number(e)]
        mask = mask | as_text.isin(extra_text) | numeric.isin(extra_numbers)
    return s.mask(mask & s.notna())


def _is_number(value) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def parse_numbers(s: pd.Series, locale_hint=None) -> pd.Series:
    """Text to numbers: currency signs and codes, thousands separators, comma decimals (`locale_hint`
    "comma" or a locale like "de", else guessed per column), `%` (kept as the number, not divided),
    `(300)` and `300-` as negatives. Unparseable values become NaN: check `parse_failures`."""
    if pd.api.types.is_numeric_dtype(s):
        return s.astype(float)
    t = _text(s).astype("string")
    t = t.str.replace(_CURRENCY, "", regex=True).str.replace("%", "", regex=False).str.strip()
    negative = t.str.fullmatch(r"\(.*\)").fillna(False) | t.str.endswith("-").fillna(False)
    t = t.str.strip("()").str.rstrip("-").str.strip()
    t = t.str.replace(r"[\s '’]", "", regex=True)
    comma_decimal = _comma_decimal(t, locale_hint)
    if comma_decimal:
        t = t.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    else:
        t = t.str.replace(",", "", regex=False)
    out = pd.to_numeric(t, errors="coerce").astype(float)
    return out.where(~negative, -out.abs())


def _comma_decimal(t: pd.Series, hint) -> bool:
    if hint is not None:
        h = str(hint).lower()
        return h in ("comma", "eu") or h[:2] in ("de", "fr", "es", "it", "nl", "pt", "ru", "pl", "tr", "da", "sv", "nb", "fi")
    sample = t.dropna()
    sample = sample[sample != ""].head(2000)
    if sample.empty:
        return False
    comma_last = sample.str.fullmatch(r"-?[\d.]*,\d{1,2}").mean()
    dot_last = sample.str.fullmatch(r"-?[\d,]*\.\d+").mean()
    return bool(comma_last > dot_last)


def parse_dates_smart(s: pd.Series, order_hint=None) -> pd.Series:
    """Text to datetimes. ISO 8601 first, then the formats for `order_hint` ("dmy", "mdy" or
    "ymd"; without a hint, day-first and month-first are both tried and the better one wins,
    month-first on a tie), then dateparser for the few values left. Failures become NaT."""
    if pd.api.types.is_datetime64_any_dtype(s):
        return s
    t = _text(s)
    present = t.notna() & (t != "")
    out = pd.to_datetime(t.where(present), format="ISO8601", errors="coerce")
    orders = [order_hint] if order_hint in _DATE_FORMATS else ["mdy", "dmy"]
    best = None
    for order in orders:
        trial = out.copy()
        for fmt in _DATE_FORMATS[order] + _DATE_FORMATS["ymd"]:
            left = present & trial.isna()
            if not left.any():
                break
            trial[left] = pd.to_datetime(t[left], format=fmt, errors="coerce")
        if best is None or trial.notna().sum() > best.notna().sum():
            best = trial
    out = best
    left = present & out.isna()
    if left.any() and left.sum() <= 500:
        import dateparser

        order = {"dmy": "DMY", "mdy": "MDY", "ymd": "YMD"}.get(order_hint or "", "MDY")
        for idx, value in t[left].items():
            parsed = dateparser.parse(str(value), settings={"DATE_ORDER": order, "PREFER_DAY_OF_MONTH": "first"})
            if parsed is not None:
                out[idx] = pd.Timestamp(parsed.replace(tzinfo=None))
    return out


def normalize_whitespace_case(s: pd.Series, mode="keep") -> pd.Series:
    """Trim, collapse inner whitespace, and apply `mode`: "title", "lower", "upper" or "keep".
    With "keep", spellings that differ only by case take the column's most frequent spelling."""
    t = _text(s)
    t = t.where(t.isna(), t.astype(str).str.replace(_SPACES, " ", regex=True))
    if mode == "title":
        return t.where(t.isna(), t.astype(str).str.title())
    if mode == "lower":
        return t.where(t.isna(), t.astype(str).str.lower())
    if mode == "upper":
        return t.where(t.isna(), t.astype(str).str.upper())
    present = t.dropna()
    if present.empty:
        return t
    # A frame, not two Series named after the column: grouping by two same-named Series can't reset its index.
    counts = pd.DataFrame({"key": present.str.lower(), "value": present}).groupby(["key", "value"]).size().reset_index(name="n")
    best = counts.sort_values(["key", "n", "value"], ascending=[True, False, True]).drop_duplicates("key")
    canonical = dict(zip(best["key"], best["value"]))
    return t.where(t.isna(), t.astype(str).str.lower().map(canonical))


def _merge_key(value) -> str:
    """A category as merges compare it: case and spacing ignored."""
    return _SPACES.sub(" ", str(value).strip().casefold())


def _merge_refusal(a, b, counts, rows):
    """Why `a` must not be merged into `b` (or the reverse): "differ only in their numbers" or "are
    both common", else None. Values equal but for case and spacing always may be. Otherwise the
    merge is refused when they differ only in their numbers ("Region 1", "Region 2"; "Region 01" and
    "Region 1" are the same number) or when both are common, each on at least 5% of the rows and on
    more than one ("Austria", "Australia"): then each is a category of its own, unless one is the
    other with an inner letter left out (`_dropped_letter`, "Wst" / "West"). A value seen once is
    never common, so a typo in a small file can still merge. `counts` maps `_merge_key` values to
    their row counts; `rows` is the column's length."""
    ka, kb = _merge_key(a), _merge_key(b)
    if ka == kb:
        return None
    if (_NUMBERS.sub("#", ka) == _NUMBERS.sub("#", kb)
            and [int(n) for n in _NUMBERS.findall(ka)] != [int(n) for n in _NUMBERS.findall(kb)]):
        return "differ only in their numbers"
    if min(counts.get(ka, 0), counts.get(kb, 0)) >= max(2, _COMMON_SHARE * rows) and not _dropped_letter(ka, kb):
        return "are both common"
    return None


def _dropped_letter(a: str, b: str) -> bool:
    """One spelling is the other with one inner letter left out ("wst" / "west"): a typo even when both
    are common. Only an inner letter, and the shorter keeps at least three letters: "sale" / "sales",
    "car" / "card" and "mr." / "mrs." are values of their own."""
    short, long_ = sorted((a, b), key=len)
    if len(long_) != len(short) + 1 or sum(ch.isalpha() for ch in short) < 3:
        return False
    return any(long_[i].isalpha() and long_[:i] + long_[i + 1:] == short for i in range(1, len(long_) - 1))


def canonicalize_categories(s: pd.Series, mapping=None, threshold=90) -> pd.Series:
    """Merge spelling variants of a category. With `mapping` ({variant: canonical}), apply it.
    Without, take values most frequent first: each joins the most similar spelling already kept
    whose rapidfuzz ratio (case and spacing ignored) is ≥ `threshold`, or is kept as a spelling of
    its own. Either way a merge `_merge_refusal` refuses (values that differ only in their numbers,
    or two common values) is left out."""
    counts = _text(s).dropna().map(_merge_key).value_counts().to_dict()
    rows = len(s)
    if mapping:
        safe = {k: v for k, v in mapping.items() if _merge_refusal(k, v, counts, rows) is None}
        return s.map(lambda v: safe.get(v, v) if pd.notna(v) else v)
    from rapidfuzz import fuzz

    canonical: dict = {}
    heads: list = []
    for value in _text(s).dropna().value_counts().index:  # most frequent first: heads are the common spellings
        key = _SPACES.sub(" ", str(value).lower())
        scored = [(fuzz.ratio(key, _SPACES.sub(" ", str(h).lower())), h) for h in heads
                  if _merge_refusal(value, h, counts, rows) is None]
        best = max(scored, key=lambda x: x[0], default=(0, None))
        if best[0] >= threshold:
            canonical[value] = best[1]
        else:
            canonical[value] = value
            heads.append(value)
    t = _text(s)
    return t.map(lambda v: canonical.get(v, v) if pd.notna(v) else v)


def extract_pattern(s: pd.Series, regex, group=1) -> pd.Series:
    """The `group` of the first match of `regex` in each value (missing where there is no match)."""
    return _text(s).astype("string").str.extract(regex, expand=True)[group - 1 if isinstance(group, int) else group].astype(object)


def fill_by_group(df: pd.DataFrame, col, by, stat="median") -> pd.Series:
    """`col` with missing values filled by the `stat` ("median", "mean" or "mode") of rows sharing
    `by` (a column or list of columns); groups with no value fall back to the whole column's."""
    keys = [by] if isinstance(by, str) else list(by)
    usable = df["_quarantine_reason"].isna() if "_quarantine_reason" in df else pd.Series(True, index=df.index)
    if stat == "mode":
        def mode(x):
            m = x.dropna().mode()
            return m.iloc[0] if len(m) else np.nan
        group = df[usable].groupby(keys, dropna=False)[col].agg(mode)
        overall = mode(df.loc[usable, col])
    else:
        group = df[usable].groupby(keys, dropna=False)[col].agg(stat)
        overall = df.loc[usable, col].agg(stat)
    filler = df[keys].merge(group.rename("_fill").reset_index(), on=keys, how="left")["_fill"]
    filler.index = df.index
    filled = df[col].fillna(filler)
    return filled.fillna(overall)


def flag_rows(df: pd.DataFrame, mask, reason) -> pd.DataFrame:
    """Mark rows for review without changing them: the reason is kept in `df.attrs["sherlock_flags"]`,
    which the sandbox reports back. The step that uses it is committed with a flag."""
    out = df.copy()
    flags = dict(out.attrs.get("sherlock_flags", {}))
    ids = out.loc[pd.Series(mask, index=out.index).fillna(False).astype(bool), "_row_id"].tolist()
    flags[str(reason)] = sorted(set(flags.get(str(reason), [])) | set(int(i) for i in ids))
    out.attrs["sherlock_flags"] = flags
    return out


def quarantine_rows(df: pd.DataFrame, mask, reason) -> pd.DataFrame:
    """Set `_quarantine_reason` on the masked rows that aren't quarantined already. Rows stay in
    the data; widgets, models and stories leave them out."""
    out = df.copy()
    m = pd.Series(mask, index=out.index).fillna(False).astype(bool) & out["_quarantine_reason"].isna()
    out["_quarantine_reason"] = out["_quarantine_reason"].astype(object)
    out.loc[m, "_quarantine_reason"] = str(reason)
    return out


def fix_encoding(s: pd.Series) -> pd.Series:
    """Repair mojibake ("CafÃ©" → "Café") with ftfy; other values are unchanged."""
    import ftfy

    return s.map(lambda v: ftfy.fix_text(v) if isinstance(v, str) else v)


def parse_failures(original: pd.Series, parsed: pd.Series) -> pd.Series:
    """Rows where `original` had a real value (not a placeholder) but the parse gave nothing."""
    had = original.notna() & ~_text(original).astype(str).str.lower().isin(SENTINELS)
    return had & parsed.isna()


def keep_outside_scope(before: pd.DataFrame, after: pd.DataFrame, rows=None, cells=()) -> pd.DataFrame:
    """`after` with its changes kept only where a scoped clean may make them: rows outside `rows`
    (a list of `_row_id`s; None means every row is in scope) and the hand-edited `cells`
    (`(_row_id, column)` pairs) take their values from `before` again. A hand-edited cell in a
    column whose type the step changed keeps the new value, since its text can't be kept.
    The Cleaner applies this to a scoped step, and the step's notebook code repeats it."""
    if rows is None and not cells:
        return after
    out = after.set_index("_row_id")
    b = before.set_index("_row_id")
    if rows is not None:
        allowed = set(int(i) for i in rows)
        outside = [i for i in b.index if i not in allowed]
        for c in [c for c in b.columns if c in out.columns]:
            if outside:
                out.loc[outside, c] = b.loc[outside, c]
    for rid, col in cells:
        if rid in out.index and col in out.columns and str(out.at[rid, col]) != str(b.at[rid, col]):
            if out[col].dtype == b[col].dtype:
                out.at[rid, col] = b.at[rid, col]
    return out.reset_index()
