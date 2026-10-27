"""Verifiers (PRD §7.3.1, TRD §7.2): check a candidate's result against the data it started from.

Hard checks (any failure scores the candidate 0, and on the full data stops the commit):
- `row_ledger`: the same rows by `_row_id`, none added or removed, `_row_id` untouched.
- `nan_introduced`: no value silently became missing. A value may go missing only if it was a
  placeholder (`N/A`, `-999`, …) or its row was quarantined (a parse failure keeps its text in lineage).
- `dtype`: no column turned into mixed Python types, and no numeric or date column turned into text.
- `pandera`: a schema derived from the starting data: the same user columns, `_row_id` unique and
  never missing, `_quarantine_reason` text.
- `parse_quarantine`: in a column that changed type, every value that didn't convert is quarantined.
- `placeholder_fill`: missing values weren't filled with a placeholder word ("Unknown", "N/A",
  "Missing", …): an empty cell stays empty unless a rule recovers its value.
- `quarantine_scope`: the step quarantined at most 2 × the issue's count + 10 rows. A step the user
  added to the cleaning plan has no detector and no count, so it may quarantine at most a fifth of
  the rows (`QUARANTINE_USER_SHARE`).
- `merge_safety`: no text value was rewritten into another value that was already in its column
  when the two differ only in their numbers or are both common (`helpers._merge_refusal`):
  "Region 2" → "Region 1" and "Austria" → "Australia" fail; "male " → "Male" passes.
- `missing_fill`: missing values stay missing (owner's decision) unless a related column recovers
  them: every filled cell must hold the one value its row's group has in this column, for some
  other column (a city → region code dependency recovers a code; a median by class doesn't). A
  step the user asked for (`requested`) may fill as it was told.

`changed` is the per-cell rule all of this counts by. `compare` sets candidates' results side by side:
the share of the cells two candidates both change where their values differ (the gate
skips over 1%, with two example cells shown both ways), and the output agreement, the share of
candidates whose results match the best one's on the cells either changes. Text compares without
case or spacing: "plan a" and "Plan A" are one value spelled two ways, not a disagreement.

`effect_line` turns a report into the cleaning log's main line for the step (cells changed, rows
quarantined, the issue's count before → after), so every number on that line comes from code.

The soft score is the mean of: parse success rate, the share of the issue resolved (the detector
re-run on the result; none for a user's step, `detector=None`), 1 − the share of cells changed outside the issue's column, and distribution
conservation for a numeric column that stays numeric (how little its median and spread moved).
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from sherlock.cleaning import detectors
from sherlock.cleaning.helpers import SENTINELS, _merge_key, _merge_refusal, parse_numbers
from sherlock.profile.datacard import build_frame

SYSTEM = ("_row_id", "_quarantine_reason")
NUMERIC_SENTINELS = {-99999.0, -9999.0, -999.0, -99.0, 999.0, 9999.0, 99999.0}
PLACEHOLDER_WORDS = SENTINELS | {
    "unknown", "not known", "not recorded", "not available", "not provided", "not specified", "unspecified",
    "no data", "missing value", "blank", "empty", "tbd", "pending", "undisclosed",
}


@dataclass
class Report:
    hard: dict[str, str] = field(default_factory=dict)       # check → "pass" | "fail: …"
    soft: dict[str, float] = field(default_factory=dict)     # component → 0..1
    parse_rate: float = 1.0
    nan_introduced: int = 0
    parse_failures: int = 0
    cells_changed: int = 0
    unrelated_changed: int = 0
    quarantined: int = 0
    issue_before: int = 0
    issue_after: int = 0

    @property
    def passed(self) -> bool:
        return all(v == "pass" for v in self.hard.values())

    @property
    def score(self) -> float:
        if not self.passed:
            return 0.0
        return round(float(np.mean(list(self.soft.values()))) if self.soft else 0.0, 4)

    def as_json(self) -> dict:
        return {
            **self.hard, "parse_rate": round(self.parse_rate, 4), "nan_introduced": self.nan_introduced,
            "parse_failures": self.parse_failures, "cells_changed": self.cells_changed,
            "unrelated_changed": self.unrelated_changed, "quarantined": self.quarantined,
            "issue_before": self.issue_before, "issue_after": self.issue_after, "score": self.score,
        }


def _duck_type(s: pd.Series) -> str:
    kind = s.dtype.kind
    if kind in "iu":
        return "BIGINT"
    if kind == "f":
        return "DOUBLE"
    if kind == "b":
        return "BOOLEAN"
    if kind == "M":
        return "TIMESTAMP"
    return "VARCHAR"


def issue_count(df: pd.DataFrame, detector: str, column: str | None) -> int:
    """Re-run one detector on a frame (usable rows only) and count its findings for the column."""
    usable = df[df["_quarantine_reason"].isna()] if "_quarantine_reason" in df else df
    user = usable.set_index("_row_id").drop(columns=[c for c in SYSTEM if c in usable and c != "_row_id"])
    types = {c: _duck_type(user[c]) for c in user.columns}
    user = user.astype(object).where(user.notna(), None)
    frame = build_frame(user, types)
    module = next(m for m in detectors.DETECTORS if m.__name__.rsplit(".", 1)[-1] == detector)
    return sum(f.count for f in module.detect(frame) if column is None or f.column == column)


def _is_placeholder(values: pd.Series) -> pd.Series:
    text = values.astype(str).str.strip().str.lower()
    numeric = pd.to_numeric(values, errors="coerce")
    return text.isin(SENTINELS) | numeric.isin(NUMERIC_SENTINELS)


def _mixed(s: pd.Series) -> bool:
    if s.dtype != object:
        return False
    kinds = {type(v).__name__ for v in s.dropna().head(5000)}
    return "str" in kinds and len(kinds) > 1  # text next to numbers, dates or bools


def changed(bc: pd.Series, ac: pd.Series) -> pd.Series:
    """The cells of a column a result changed. A retype compares as text, so '22' → 22 isn't a change."""
    try:
        differs = ~((bc == ac) | (bc.isna() & ac.isna()))
    except (TypeError, ValueError):
        differs = bc.astype(str) != ac.astype(str)
    if bc.dtype != ac.dtype:
        differs = (bc.astype(str).str.strip() != ac.astype(str).str.replace(r"\.0$", "", regex=True)) & ~(bc.isna() & ac.isna())
    return differs


def verify(before: pd.DataFrame, after: pd.DataFrame, detector: str | None, column: str | None,
           requested: bool = False) -> Report:
    r = Report()
    # --- row ledger -------------------------------------------------------------------------
    if "_row_id" not in after or len(after) != len(before) or set(after["_row_id"]) != set(before["_row_id"]):
        r.hard["row_ledger"] = f"fail: {len(before)} rows in, {len(after) if '_row_id' in after else '?'} out"
        r.hard["pandera"] = "fail: skipped"
        return r
    r.hard["row_ledger"] = "pass"
    b = before.set_index("_row_id")
    a = after.set_index("_row_id").reindex(b.index)

    # --- pandera schema from the starting data ---------------------------------------------------
    r.hard["pandera"] = _pandera(b, a)
    if r.hard["pandera"] != "pass":
        return r

    quarantined_now = a["_quarantine_reason"].notna() & b["_quarantine_reason"].isna()
    r.quarantined = int(quarantined_now.sum())
    user_cols = [c for c in b.columns if c not in SYSTEM]
    changed_total = 0
    unrelated = 0
    nan_new = 0
    dtype_problem = None
    parse_failures = 0
    parse_attempts = 0
    for c in user_cols:
        bc, ac = b[c], a[c]
        went_missing = bc.notna() & ac.isna()
        legit = _is_placeholder(bc) | quarantined_now
        nan_new += int((went_missing & ~legit).sum())
        n = int(changed(bc, ac).sum())
        changed_total += n
        if column is not None and c != column:
            unrelated += n
        if _mixed(ac) and not _mixed(bc):
            dtype_problem = f"fail: {c} holds mixed types"
        if bc.dtype.kind in "iufM" and ac.dtype == object and not ac.dropna().empty:
            dtype_problem = f"fail: {c} turned from {bc.dtype} into text"
        if bc.dtype == object and ac.dtype.kind in "iufMb":
            had = bc.notna() & ~_is_placeholder(bc)
            failed = had & ac.isna()
            parse_attempts += int(had.sum())
            parse_failures += int((failed & ~a["_quarantine_reason"].notna()).sum())
    r.nan_introduced = nan_new
    r.cells_changed = changed_total
    r.unrelated_changed = unrelated
    r.parse_failures = parse_failures
    r.parse_rate = 1.0 - (parse_failures / parse_attempts) if parse_attempts else 1.0
    r.hard["nan_introduced"] = "pass" if nan_new == 0 else f"fail: {nan_new} values became empty"
    r.hard["dtype"] = dtype_problem or "pass"
    r.hard["parse_quarantine"] = "pass" if parse_failures == 0 else f"fail: {parse_failures} unparsed values not quarantined"
    r.hard["placeholder_fill"] = _placeholder_fill(b, a, user_cols)
    r.hard["merge_safety"] = _merge_safety(b, a, user_cols)
    r.hard["missing_fill"] = "pass" if requested else _missing_fill(b, a, user_cols, quarantined_now)

    # --- soft score -------------------------------------------------------------------------------
    r.soft["parse_rate"] = r.parse_rate
    counted = False
    if detector:
        try:
            r.issue_before = issue_count(before, detector, column)
            r.issue_after = issue_count(after, detector, column)
            r.soft["resolved"] = 1.0 - (r.issue_after / r.issue_before) if r.issue_before else 1.0
            counted = True
        except Exception:  # a detector that can't run on the result counts as unresolved
            r.soft["resolved"] = 0.0
    r.hard["quarantine_scope"] = _quarantine_scope(r.quarantined, r.issue_before if counted else None,
                                                   rows=len(b) if detector is None else None)
    total_cells = max(len(b) * max(len(user_cols), 1), 1)
    r.soft["unrelated"] = 1.0 - min(1.0, unrelated / max(changed_total, 1)) if changed_total else 1.0
    if column in b and pd.api.types.is_numeric_dtype(b[column]) and pd.api.types.is_numeric_dtype(a[column]):
        r.soft["distribution"] = _conservation(b[column], a[column])
    r.soft["unrelated"] = min(r.soft["unrelated"], 1.0 - unrelated / total_cells)
    return r


def _n(count: int, one: str, many: str) -> str:
    return f"{count:,} {one if count == 1 else many}"


def effect_line(report: Report, issue_words: str | None) -> str:
    """The cleaning log's main line for a step, built from its full-data report and never from the
    model's words (TRD §7.2): "Changed 263 cells, quarantined 4 rows; 263 → 0 missing values".
    `issue_words` names what the detector counts; a user's step (no detector) has no count to show."""
    parts = []
    if report.cells_changed:
        parts.append(f"changed {_n(report.cells_changed, 'cell', 'cells')}")
    if report.quarantined:
        parts.append(f"quarantined {_n(report.quarantined, 'row', 'rows')}")
    line = ", ".join(parts) or "changed nothing"
    line = line[0].upper() + line[1:]
    if issue_words:
        line += f"; {report.issue_before:,} → {report.issue_after:,} {issue_words}"
    return line


AGREE_SHARE = 0.01  # results that differ on at most 1% of the cells they change agree
LONE_AGREEMENT = 0.5  # the agreement of a result no other candidate's result could confirm


def _as_text(s: pd.Series) -> pd.Series:
    """Values as text for comparing two results: a whole float as an integer, a midnight as its date,
    and text without case or spacing (`helpers._merge_key`), since a case or spacing variant of one
    value is the same value."""
    if s.dtype.kind == "M":
        return s.dt.strftime("%Y-%m-%d").where(s.dt.normalize() == s, s.astype(str))
    return s.astype(str).str.replace(r"\.0$", "", regex=True).map(_merge_key)


def results_differ(x: pd.Series, y: pd.Series) -> pd.Series:
    """The cells where two candidates' results differ: numbers within a relative 1e-9, both missing
    as equal, dates and booleans by value, otherwise as text without case or spacing. A number and a
    text that reads as the same number (19.0 and "$19.00") are one value written two ways."""
    both_missing = x.isna() & y.isna()
    one_missing = x.isna() != y.isna()
    if (x.dtype.kind in "iuf") != (y.dtype.kind in "iuf") and "b" not in (x.dtype.kind, y.dtype.kind):
        number, text = (x, y) if x.dtype.kind in "iuf" else (y, x)
        read = parse_numbers(text.astype(object).where(text.notna(), None))
        if read.notna().any():  # the text side reads as numbers: compare those numbers
            y_num, x_num = (read, number) if x is number else (number, read)
            return results_differ(x_num.astype(float), y_num.astype(float))
    if x.dtype.kind in "iuf" and y.dtype.kind in "iuf":
        close = np.isclose(x.astype(float), y.astype(float), rtol=1e-9, atol=0.0)
        return pd.Series(~close, index=x.index) & ~both_missing | one_missing
    if x.dtype == y.dtype and x.dtype.kind in "Mb":
        return ~((x == y) | both_missing)
    return ((_as_text(x) != _as_text(y)) & ~both_missing) | one_missing


def show(value) -> str:
    """A value as the log shows it in a two-way example: a date as "3 Apr 2021", a whole number
    without ".0", a missing one as "empty"."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return "empty"
    if isinstance(value, pd.Timestamp):
        day = f"{value.day} {value:%b %Y}"
        return day if value == value.normalize() else f"{day} {value:%H:%M}"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


@dataclass
class Comparison:
    agreement: float                  # share of candidates whose results match the best one's
    disagreement: float = 0.0         # the worst pair: share of the cells both change, valued apart
    pair: tuple[int, int] | None = None
    examples: list[tuple[str, str, str]] = field(default_factory=list)  # (before, one, other), at most two


def compare(before: pd.DataFrame, results: list[pd.DataFrame | None], best: int) -> Comparison:
    """Candidates' results on the same rows side by side. `results[i]` is candidate i's
    result, or None when it failed its checks. Every pair of results is compared on the cells both
    changed: the worst pair's share of those cells with different values is the disagreement, with
    up to two of them as examples. The agreement is the share of all candidates (failed ones count
    as not agreeing) whose result differs from the best one's on at most 1% of the cells either
    changed; the best agrees with itself. With fewer than two passing results nothing confirms the
    best one, so its agreement is at most a neutral 0.5 (`LONE_AGREEMENT`), not a full 1.0."""
    b = before.set_index("_row_id")
    cols = [c for c in b.columns if c not in SYSTEM]
    frames = {i: r.set_index("_row_id").reindex(b.index) for i, r in enumerate(results) if r is not None}
    masks = {i: {c: changed(b[c], f[c]).to_numpy(bool) for c in cols if c in f} for i, f in frames.items()}
    out = Comparison(agreement=0.0)
    for i in frames:
        for j in frames:
            if j <= i:
                continue
            both = differ = 0
            cells = []
            for c in cols:
                if c not in masks[i] or c not in masks[j]:
                    continue
                shared = masks[i][c] & masks[j][c]
                if not shared.any():
                    continue
                apart = shared & results_differ(frames[i][c], frames[j][c]).to_numpy(bool)
                both += int(shared.sum())
                differ += int(apart.sum())
                cells += [(rid, c) for rid in b.index[apart][: 2 - len(cells)]] if len(cells) < 2 else []
            share = differ / both if both else 0.0
            if share > out.disagreement:
                out.disagreement, out.pair = share, (i, j)
                out.examples = [(show(b.at[r, c]), show(frames[i].at[r, c]), show(frames[j].at[r, c])) for r, c in cells]
    agree = 0
    for k in range(len(results)):
        if k == best:
            agree += 1
            continue
        if k not in frames or best not in frames:
            continue
        either = differ = 0
        for c in cols:
            if c not in masks[k] or c not in masks[best]:
                continue
            union = masks[k][c] | masks[best][c]
            either += int(union.sum())
            differ += int((union & results_differ(frames[k][c], frames[best][c]).to_numpy(bool)).sum())
        if either == 0 or differ / either <= AGREE_SHARE:
            agree += 1
    out.agreement = agree / len(results) if results else 0.0
    if len(frames) < 2:  # a lone passing result has nothing to agree with: neutral, not full
        out.agreement = min(out.agreement, LONE_AGREEMENT)
    return out


QUARANTINE_FACTOR = 2
QUARANTINE_MARGIN = 10
QUARANTINE_USER_SHARE = 0.2


def _quarantine_scope(quarantined: int, issue_count: int | None, rows: int | None = None) -> str:
    """A step may quarantine at most twice as many rows as its issue has, plus a small margin
    (owner's decision, 2026-10-25). Live, a NaN comparison in a model's mask quarantined 1,020 of
    1,309 rows for a 4-row issue and still committed with a flag (Day 3 review H1). A user's step
    (`rows` given, no issue to count) may quarantine at most a fifth of the rows."""
    if rows is not None:
        return "pass" if quarantined <= QUARANTINE_USER_SHARE * rows else "fail: quarantines more than a fifth of the rows"
    if issue_count is None or quarantined <= QUARANTINE_FACTOR * issue_count + QUARANTINE_MARGIN:
        return "pass"
    return f"fail: {quarantined:,} rows quarantined for an issue in {issue_count:,}"


def _placeholder_fill(b: pd.DataFrame, a: pd.DataFrame, columns: list[str]) -> str:
    """Missing cells that became a placeholder word, in any column."""
    for c in columns:
        filled = b[c].isna() & a[c].notna()
        if not filled.any():
            continue
        words = a.loc[filled, c]
        placeholder = words.map(lambda v: isinstance(v, str) and v.strip().lower() in PLACEHOLDER_WORDS)
        if placeholder.any():
            example = words[placeholder].iloc[0]
            return f"fail: {int(placeholder.sum())} missing values in {c} filled with the placeholder {example!r}"
    return "pass"


def _merge_safety(b: pd.DataFrame, a: pd.DataFrame, columns: list[str]) -> str:
    """Text values rewritten into another value already in the column, where the merge rule refuses
    the pair (values that differ only in their numbers, or two common values)."""
    for c in columns:
        if b[c].dtype != object or a[c].dtype != object:
            continue
        rewritten = b[c].notna() & a[c].notna() & (b[c].astype(str) != a[c].astype(str))
        if not rewritten.any():
            continue
        counts = b[c].dropna().astype(str).map(_merge_key).value_counts().to_dict()
        for old, new in pd.DataFrame({"old": b.loc[rewritten, c], "new": a.loc[rewritten, c]}).drop_duplicates().itertuples(index=False):
            if not (isinstance(old, str) and isinstance(new, str)) or _merge_key(new) not in counts:
                continue  # a new spelling, or not text: not a merge of two existing values
            why = _merge_refusal(old, new, counts, len(b))
            if why:
                return f"fail: merged {old!r} into {new!r}, which {why}"
    return "pass"


def _missing_fill(b: pd.DataFrame, a: pd.DataFrame, columns: list[str], quarantined: pd.Series) -> str:
    """Missing cells that became values no related column recovers. A filled cell is recovered when,
    for some other column, the rows sharing its value there (missing in neither column) hold one
    value in this column, and the fill is that value."""
    for c in columns:
        filled = b[c].isna() & a[c].notna() & ~quarantined
        if not filled.any():
            continue
        target = a[c].where(~filled)  # the values that were there before, the only evidence a rule can use
        open_cells = filled.copy()
        for other in columns:
            if other == c or not open_cells.any():
                continue
            key = b[other]
            known = target.notna() & key.notna()
            if not known.any():
                continue
            groups = pd.DataFrame({"k": key[known].astype(str), "v": target[known].astype(str)}).groupby("k")["v"]
            single = groups.nunique()
            single = single[single == 1].index
            only = groups.first()
            rows = open_cells & key.notna() & key.astype(str).isin(single)
            if not rows.any():
                continue
            expected = key[rows].astype(str).map(only)
            got = a.loc[rows, c].astype(str)
            same = _same_text(got, expected)
            open_cells.loc[same[same].index] = False
        n = int(open_cells.sum())
        if n:
            example = a.loc[open_cells, c].iloc[0]
            return (f"fail: {n} missing values in {c} filled with values no related column recovers "
                    f"(such as {show(example)}); missing values stay missing")
    return "pass"


def _same_text(x: pd.Series, y: pd.Series) -> pd.Series:
    """Two columns of the same cells as text, numbers equal when they parse to the same float."""
    nx, ny = pd.to_numeric(x, errors="coerce"), pd.to_numeric(y, errors="coerce")
    both = nx.notna() & ny.notna()
    out = x == y
    out[both] = np.isclose(nx[both], ny[both], rtol=1e-9, atol=1e-12)
    return out


def _conservation(before: pd.Series, after: pd.Series) -> float:
    b, a = before.dropna().astype(float), after.dropna().astype(float)
    if b.empty or a.empty:
        return 1.0
    spread = float(b.std()) or 1.0
    shift = abs(float(a.median()) - float(b.median())) / spread
    ratio = float(a.std()) / spread if spread else 1.0
    return float(max(0.0, 1.0 - shift - abs(1.0 - ratio)))


def _pandera(b: pd.DataFrame, a: pd.DataFrame) -> str:
    import pandera.pandas as pa

    expected = [c for c in b.columns if c not in SYSTEM]
    missing = [c for c in expected if c not in a.columns]
    if missing:
        return f"fail: columns removed: {', '.join(missing[:5])}"
    schema = pa.DataFrameSchema(
        {"_quarantine_reason": pa.Column(object, nullable=True, coerce=False, required=True,
                                         checks=pa.Check(lambda s: s.dropna().map(lambda v: isinstance(v, str)).all()))},
        index=pa.Index(int, unique=True, nullable=False, coerce=True),
        strict=False,
    )
    try:
        schema.validate(a.assign(_quarantine_reason=a["_quarantine_reason"].astype(object)), lazy=False)
    except pa.errors.SchemaError as exc:
        return f"fail: {str(exc).splitlines()[0][:200]}"
    return "pass"
