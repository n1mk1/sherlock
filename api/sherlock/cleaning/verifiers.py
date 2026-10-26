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

The soft score is the mean of: parse success rate, the share of the issue resolved (the detector
re-run on the result; none for a user's step, `detector=None`), 1 − the share of cells changed outside the issue's column, and distribution
conservation for a numeric column that stays numeric (how little its median and spread moved).
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from sherlock.cleaning import detectors
from sherlock.cleaning.helpers import SENTINELS
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


def verify(before: pd.DataFrame, after: pd.DataFrame, detector: str | None, column: str | None) -> Report:
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
        try:
            differs = ~((bc == ac) | (bc.isna() & ac.isna()))
        except (TypeError, ValueError):
            differs = bc.astype(str) != ac.astype(str)
        if bc.dtype != ac.dtype:  # a retype: compare as text, so '22' → 22 isn't a change
            differs = (bc.astype(str).str.strip() != ac.astype(str).str.replace(r"\.0$", "", regex=True)) & ~(bc.isna() & ac.isna())
        n = int(differs.sum())
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
