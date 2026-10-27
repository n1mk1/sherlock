"""Leakage candidates: columns that record the outcome, so a model using them would cheat.

For each target-like column, a column leaks when either
- its values (missing as its own value) predict the target with ≥ 95% accuracy and at least
  20 points above always guessing the majority class (low-cardinality columns only), or
- whether it is filled in predicts the target: the filled rows (5–95% of rows) are ≥ 98% one
  class, and that class is at least 20 points rarer among the empty rows.
"""

import pandas as pd

from sherlock.cleaning.detectors.base import DetectorSpec, Finding, Frame, Injector
from sherlock.cleaning.detectors.fixtures import clean_frame

ACCURACY = 0.95
PURITY = 0.98
LIFT = 0.2
MAX_UNIQUE_RATIO = 0.5
MIN_COVERAGE, MAX_COVERAGE = 0.05, 0.95


def _value_rule(key, y) -> float | None:
    accuracy = pd.crosstab(key, y).max(axis=1).sum() / len(y)
    baseline = y.value_counts(normalize=True).iloc[0]
    return accuracy if accuracy >= ACCURACY and accuracy - baseline >= LIFT else None


def _presence_rule(filled, y) -> float | None:
    share = filled.mean()
    if not MIN_COVERAGE <= share <= MAX_COVERAGE:
        return None
    filled_counts = y[filled].value_counts(normalize=True)
    cls, purity = filled_counts.index[0], filled_counts.iloc[0]
    empty_rate = (y[~filled] == cls).mean()
    return purity if purity >= PURITY and purity - empty_rate >= LIFT else None


def detect(frame: Frame) -> list[Finding]:
    findings = []
    for target in frame.target_candidates:
        y_all = frame.df[target]
        known = y_all.notna()
        y = y_all[known].astype(str)
        if y.nunique() < 2:
            continue
        for name, col in frame.columns.items():
            if name == target or col.role in ("id", "empty"):
                continue
            x = frame.df.loc[known, name]
            filled = x.notna()
            score, reason = None, None
            unique_ratio = x.nunique() / max(int(filled.sum()), 1)
            if unique_ratio <= MAX_UNIQUE_RATIO:
                score = _value_rule(x.astype(str).where(filled, "<missing>"), y)
                reason = "values"
            if score is None:
                score, reason = _presence_rule(filled, y), "presence"
            if score is not None:
                findings.append(Finding(
                    "leakage", name, int(filled.sum()),
                    f"Exclude {name} from models that predict {target}; it records the outcome.",
                    details={"target": target, "score": round(float(score), 4), "rule": reason,
                             "reason": f"near-perfect predictor of {target} ({score:.2f})"},
                ))
    return findings


def found_fixture():
    """A column that copies the yes/no target in other words."""
    df = clean_frame()
    df.insert(len(df.columns) - 1, "result_code", ["A" if v == "yes" else "B" for v in df["flag"]])
    return df


SPEC = DetectorSpec(
    "leakage", "records the outcome", "Columns that record the outcome, so a model using them would cheat.",
    group="other", weight=1.0, default_level=None, scope="column", detect=detect, depth=5,
    never_change="Records the outcome, so it is marked as leakage and not changed", skip_text="excluded from models",
    marks_column="leakage_candidates",
    found_fixture=found_fixture,
)
