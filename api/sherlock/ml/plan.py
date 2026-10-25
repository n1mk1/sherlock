"""The common path of an ML run before any model (TRD §7.5 steps 1–3, PRD ML-3): the scope's rows,
the task, the features and every exclusion with its reason.

Everything here is code over the version's data and its DataCard; the model never chooses a
feature. A run's plan is stored with the run and rendered into its `repro.py`, so the notebook
selects exactly the same rows and columns.
"""

import re
from dataclasses import dataclass, field

import duckdb
import numpy as np
import pandas as pd

from sherlock.errors import ApiError
from sherlock.rows.query import ident

MIN_ROWS = 100           # supervised recipes refuse below this (PRD ML-10)
FOLDS = 5                # the default number of cross-validation folds (core.FOLDS)
SAMPLE_ROWS = 50_000     # larger scopes are sampled, stratified, with the seed (TRD §6.7)
HIGH_CARDINALITY = 50
GROUP_SHARE = 0.25       # an ID-like group column has at least this many values per filled row
SEED = 42


@dataclass
class Plan:
    target: str
    task: str                     # classification | regression
    metric: str                   # accuracy | macro_f1 | r2
    rows_sql: str                 # the WHERE clause of the scope (quarantine excluded)
    features: list[str]
    numeric: list[str]
    categorical: list[str]        # one-hot (≤ 50 values)
    high_card: list[str]          # target-encoded inside the folds (> 50 values)
    excluded: list[dict] = field(default_factory=list)  # [{column, reason}]
    rows: dict = field(default_factory=dict)            # {total, with_target, blank_target, used}
    sample: dict | None = None    # {seed, stratify_column, n} when sampled
    classes: list | None = None
    forced: list[dict] = field(default_factory=list)    # [{column, reason}] put back in by the user despite a check
    group: str | None = None      # rows sharing a value of this column stay in one fold (step 4)

    def json(self) -> dict:
        return {k: getattr(self, k) for k in ("target", "task", "metric", "rows_sql", "features", "numeric", "categorical",
                                              "high_card", "excluded", "rows", "sample", "classes", "forced", "group")}


def task_for(series: pd.Series, col_type: str) -> str:
    """bool/category/text → classification; numbers with more than 20 values → regression, else classification."""
    if col_type in ("int", "float") and series.dropna().nunique() > 20:
        return "regression"
    return "classification"


def load_scope(conn: duckdb.DuckDBPyConnection, rows_sql: str) -> pd.DataFrame:
    return conn.execute(f"SELECT * FROM t WHERE {rows_sql} ORDER BY _row_id").df()


def make_plan(df: pd.DataFrame, card: dict, rows_sql: str, target: str, chosen: list[str] | None = None,
              forced: list[str] | None = None, n_folds: int = FOLDS) -> Plan:
    """Frame the task and pick the features. `chosen` is the setup form's chips when the user changed
    them (None: every column is a candidate); a column left out of it is excluded as "turned off in the
    setup". `forced` re-includes columns the checks excluded (the form warns first; the model card
    keeps a warning). Each outcome needs a row in every fold (`n_folds`), or held-out scores such as
    AUC can't be computed."""
    cols = {c["name"]: c for c in card["columns"]}
    if target not in cols:
        raise ApiError(422, "invalid", f"There's no column {target!r} to explain.")
    y = df[target]
    with_target = int(y.notna().sum())
    if with_target < MIN_ROWS:
        raise ApiError(422, "invalid", f"This needs at least {MIN_ROWS} rows with {target} filled in; the scope has {with_target}.")
    task = task_for(y, cols[target]["type"])
    classes = sorted(y.dropna().unique().tolist(), key=str) if task == "classification" else None
    if task == "classification" and len(classes) < 2:
        raise ApiError(422, "invalid", f"{target} has a single value in these rows, so there's nothing to explain.")
    if task == "classification":
        counts = y.dropna().astype(str).value_counts()
        if counts.iloc[-1] < n_folds:
            raise ApiError(422, "invalid", f"Each value of {target} needs at least {n_folds} rows, one per fold of the "
                                           f"cross-validation; {counts.index[-1]!r} has {int(counts.iloc[-1])}.")
    metric = "r2" if task == "regression" else ("accuracy" if len(classes) == 2 else "macro_f1")

    leak = {lc["column"]: lc["reason"] for lc in card.get("leakage_candidates") or [] if lc.get("target") in (None, target)}
    excluded, features, kept_anyway = [], [], []
    forced = set(forced or [])
    yn = pd.to_numeric(y, errors="coerce") if task == "regression" or (classes and all(isinstance(c, (int, float, bool, np.bool_)) for c in classes)) else None
    for name, c in cols.items():
        if name == target or name not in df.columns:
            continue
        reason = None
        if c["role"] == "empty":
            reason = "has no values"
        elif c["role"] == "id" or c["type"] == "id":
            reason = "ID-like: unique per row"
        elif c["role"] == "free_text":
            reason = "free text"
        elif c["type"] in ("date", "datetime"):
            reason = "a date (dates aren't used as features yet)"
        elif name in leak:
            reason = f"records the outcome (leakage): {leak[name]}"
        elif names_target(name, target):
            reason = f"derived from {target} (its name contains it)"
        elif task == "classification" and c["type"] not in ("int", "float") and _pure(df[name], y):
            reason = f"each of its values goes with one {target} value (leakage)"
        elif yn is not None and c["type"] in ("int", "float"):
            x = pd.to_numeric(df[name], errors="coerce")
            ok = x.notna() & yn.notna()
            if ok.sum() > 10 and x[ok].std() > 0 and yn[ok].std() > 0 and abs(float(x[ok].corr(yn[ok]))) > 0.98:
                reason = f"tracks {target} almost exactly (|correlation| above 0.98)"
        if chosen is not None and name not in chosen and name not in forced:
            excluded.append({"column": name, "reason": reason or "turned off in the setup"})
        elif reason and name not in forced:
            excluded.append({"column": name, "reason": reason})
        else:
            features.append(name)
            if reason:
                kept_anyway.append({"column": name, "reason": reason})
    if not features:
        raise ApiError(422, "invalid", "No column is left to explain it with after the checks.")
    numeric = [f for f in features if cols[f]["type"] in ("int", "float") and cols[f]["role"] == "measure"]
    rest = [f for f in features if f not in numeric]
    high = [f for f in rest if df[f].nunique(dropna=True) > HIGH_CARDINALITY]
    categorical = [f for f in rest if f not in high]
    rows = {"total": int(len(df)), "with_target": with_target, "blank_target": int(len(df) - with_target),
            "used": min(with_target, SAMPLE_ROWS)}
    sample = {"seed": SEED, "stratify_column": target if task == "classification" else None, "n": SAMPLE_ROWS} \
        if with_target > SAMPLE_ROWS else None
    return Plan(target, task, metric, rows_sql, features, numeric, categorical, high, excluded, rows, sample, classes,
                kept_anyway, group_column(df[y.notna()], high))


def group_column(df: pd.DataFrame, high_card: list[str]) -> str | None:
    """The column whose rows stay together in the folds (TRD §7.5 step 4): of the target-encoded
    columns whose values repeat, the one with the most values, when they number at least a quarter of
    its filled rows, so most groups are a few rows (a ticket, an account, a household). A target-encoded
    column's held-out rows would otherwise be encoded from their own group's outcomes. None when no
    column is like that."""
    best = None
    for c in high_card:
        s = df[c].dropna()
        distinct = int(s.nunique())
        if len(s) and distinct < len(s) and distinct >= GROUP_SHARE * len(s) and (best is None or distinct > best[1]):
            best = (c, distinct)
    return best[0] if best else None


def _words(name: str) -> list[str]:
    """A column name's words: split at anything not a letter or digit, and at camelCase."""
    return [w for w in re.split(r"[^a-z0-9]+", re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name).lower()) if w]


def names_target(name: str, target: str) -> bool:
    """A column whose name contains the target's: anywhere for a target name of four or more letters
    and digits ("survived" in "survivedcount"), as whole words for a shorter one, so "age" matches
    "age_group" but not "page_views", and "y" matches "y_hat" but not "day"."""
    stem = re.sub(r"[^a-z0-9]", "", target.lower())
    if len(stem) >= 4:
        return stem in re.sub(r"[^a-z0-9]", "", name.lower())
    words, tw = _words(name), _words(target)
    return bool(tw) and any(words[i:i + len(tw)] == tw for i in range(len(words)))


def _pure(x: pd.Series, y: pd.Series) -> bool:
    """A category that settles the outcome by itself: on rows with both, each of its (fewer than
    one per ten rows) values goes with a single outcome at least 98% of the time, while the outcome
    alone is far from that predictable."""
    ok = x.notna() & y.notna()
    if ok.sum() < 20 or x[ok].nunique() > max(2, ok.sum() // 10):
        return False
    counts = pd.crosstab(x[ok].astype(str), y[ok].astype(str))
    purity = counts.max(axis=1).sum() / counts.values.sum()
    majority = counts.sum(axis=0).max() / counts.values.sum()
    return purity >= 0.98 and majority < 0.95


def scope_sql(rows_sql: str) -> str:
    return f"SELECT * FROM t WHERE {rows_sql} ORDER BY _row_id"


__all__ = ["Plan", "make_plan", "load_scope", "scope_sql", "ident", "MIN_ROWS"]
