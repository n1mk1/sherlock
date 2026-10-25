"""Interestingness, scored in code (TRD §7.3 step 2), and each candidate's fact candidates.

Each candidate's query runs on the full version (which also validates it); the statistics run on a
reservoir sample of at most 200,000 usable rows. The parts, each 0–1, are weighted 0.35 variance
explained (η² of the charted value by its category), 0.1 skew, 0.2 trend strength (Kendall τ), 0.1
outlier share, 0.15 correlation strength and 0.1 coverage (non-missing share). Which parts apply
depends on the chart:
- a target's rate by a category: η² of the target
- a measure by a category: η² of the measure, halved when the file has a target
- row counts by a category: a quarter of their unevenness (one minus normalized entropy) in the η² slot
- a KPI of a measure: its skew and outlier share
- a target's rate KPI: half of how far the rate is from 0 or 1
- a trend: Kendall τ
- a histogram: its skew and outlier share; a box plot: half the η² of the measure by the category and
  its outlier share; a heatmap: 0.8 of the η² of the target by the two categories together; a
  scatter: the |correlation| of its two measures (D6.5)
"""

import math

import duckdb
import numpy as np
import pandas as pd

from sherlock.dashboard.candidates import MAX_COLUMNS, Candidate, Target, binary_target
from sherlock.rows.query import ident
from sherlock.widgets.compile import compile_sql, rows_clause
from sherlock.widgets.execute import run_query

WEIGHTS = {"variance": 0.35, "skew": 0.1, "trend": 0.2, "outliers": 0.1, "correlation": 0.15, "coverage": 0.1}
SAMPLE_ROWS = 200_000
RANK_SAMPLE_ROWS = 20_000


def sample_frame(conn: duckdb.DuckDBPyConnection, columns: list[str], n: int = SAMPLE_ROWS) -> pd.DataFrame:
    cols = ", ".join(ident(c) for c in columns) or "1 AS _one"
    return conn.execute(
        f"SELECT * FROM (SELECT {cols} FROM t WHERE _quarantine_reason IS NULL) AS s "
        f"USING SAMPLE {int(n)} ROWS (reservoir, 42)"
    ).df()


def _indicator(df: pd.DataFrame, target: Target, card: dict) -> pd.Series:
    col = df[target.name]
    if target.value is not None:
        return pd.to_numeric(col, errors="coerce").eq(target.value).astype(float).where(col.notna())
    if pd.api.types.is_bool_dtype(col) or pd.api.types.is_numeric_dtype(col):
        return pd.to_numeric(col, errors="coerce").astype(float)
    pos = target.positive.split(" = ", 1)[-1]
    return col.astype("string").eq(pos).astype(float).where(col.notna())


def eta_squared(values: pd.Series, groups: pd.Series) -> float:
    ok = values.notna() & groups.notna()
    v, g = values[ok].astype(float), groups[ok]
    if len(v) < 3 or v.var() == 0 or g.nunique() < 2:
        return 0.0
    mean = v.mean()
    by = v.groupby(g)
    between = float((by.count() * (by.mean() - mean) ** 2).sum())
    total = float(((v - mean) ** 2).sum())
    return max(0.0, min(1.0, between / total)) if total else 0.0


def kendall_tau(series: list[float]) -> float:
    """|τ| of a series against its order, ties counted as neither (τ-a)."""
    xs = [x for x in series if x is not None and not (isinstance(x, float) and math.isnan(x))]
    n = len(xs)
    if n < 3:
        return 0.0
    xs = xs[-400:]
    n = len(xs)
    a = np.asarray(xs, dtype=float)
    diff = np.sign(a[None, :] - a[:, None])
    concordant_minus_discordant = float(np.triu(diff, 1).sum())
    return abs(concordant_minus_discordant) / (n * (n - 1) / 2)


def outlier_share(values: pd.Series) -> float:
    v = pd.to_numeric(values, errors="coerce").dropna()
    if len(v) < 10:
        return 0.0
    q1, q3 = v.quantile(0.25), v.quantile(0.75)
    iqr = q3 - q1
    if iqr == 0:
        return 0.0
    share = float(((v < q1 - 1.5 * iqr) | (v > q3 + 1.5 * iqr)).mean())
    return min(1.0, share / 0.1)


def unevenness(counts: list[float]) -> float:
    total = sum(counts)
    if total <= 0 or len(counts) < 2:
        return 0.0
    p = np.asarray(counts, dtype=float) / total
    p = p[p > 0]
    return float(1 - (-(p * np.log(p)).sum()) / math.log(len(counts)))


def coverage(card: dict, columns: list[str]) -> float:
    if not columns:
        return 1.0
    by_name = {c["name"]: c for c in card["columns"]}
    return float(np.mean([1 - (by_name[c]["missing_pct"] or 0) / 100 for c in columns if c in by_name]))


def rank_columns(conn: duckdb.DuckDBPyConnection, card: dict) -> list[str] | None:
    """For a file with more than 30 usable columns: the 30 most informative, keeping the target, time
    and first ID columns. None when the file isn't wide."""
    usable = [c for c in card["columns"] if c["role"] != "empty"]
    if len(usable) <= MAX_COLUMNS:
        return None
    target = binary_target(card)
    df = sample_frame(conn, [c["name"] for c in usable], RANK_SAMPLE_ROWS)
    ind = _indicator(df, target, card) if target else None
    keep = [c["name"] for c in usable if c["role"] == "time" or (target and c["name"] == target.name)]
    keep += [c["name"] for c in usable if c["role"] == "id"][:1]
    scores = {}
    for c in usable:
        name = c["name"]
        if name in keep:
            continue
        col = df[name]
        if ind is not None:
            if c["role"] == "measure":
                x = pd.to_numeric(col, errors="coerce")
                ok = x.notna() & ind.notna()
                scores[name] = abs(float(x[ok].corr(ind[ok]))) if ok.sum() > 2 and x[ok].std() > 0 else 0.0
            else:
                scores[name] = eta_squared(ind, col) if (c["distinct"] or 0) <= 50 else 0.0
        else:
            if c["role"] == "measure":
                x = pd.to_numeric(col, errors="coerce").dropna()
                scores[name] = min(1.0, float(x.std() / abs(x.mean()))) if len(x) > 2 and x.mean() else 0.0
            else:
                counts = col.value_counts().tolist()
                scores[name] = 1 - unevenness(counts) if 2 <= len(counts) <= 50 else 0.0
        if math.isnan(scores[name]):
            scores[name] = 0.0
    ranked = sorted(scores, key=lambda n: -scores[n])
    chosen = set(keep + ranked[: max(0, MAX_COLUMNS - len(keep))])
    return [c["name"] for c in usable if c["name"] in chosen]


def _facts(cand: Candidate, result: dict) -> None:
    """The top and bottom elements of a chart (TRD §7.3 step 3), and the accent ("the point")."""
    names = [c["name"] for c in result["columns"]]
    rows = result["rows"]
    if cand.view == "kpi" or not rows:
        if rows:
            cand.facts = {"value": rows[0][0]}
        return
    if cand.view in ("histogram", "scatter"):
        cand.facts = {"elements": []}  # the chart accents its own peak; there's no category to name
        return
    if cand.view == "table":
        cand.facts = {"first": rows[0][0]}
        cand.point = {"kind": "cell", "key": str(rows[0][0])}
        return
    y = names.index(cand.options.get("y")) if cand.options.get("y") in names else 1
    pairs = [(r[0], r[y]) for r in rows if r[y] is not None]
    if not pairs:
        return
    top = max(pairs, key=lambda p: p[1])
    bottom = min(pairs, key=lambda p: p[1])
    cand.facts = {"top": {"key": str(top[0]), "value": top[1]}, "bottom": {"key": str(bottom[0]), "value": bottom[1]},
                  "elements": [str(p[0]) for p in pairs[:20]]}
    cand.point = {"kind": "point" if cand.view in ("line", "area") else "bar", "key": str(top[0])}


def score(conn: duckdb.DuckDBPyConnection, card: dict, cands: list[Candidate]) -> list[Candidate]:
    """Run, score and keep the candidates whose query works and returns rows, best first."""
    target = binary_target(card)
    needed = sorted({c for cand in cands for c in cand.columns})
    df = sample_frame(conn, needed) if needed else pd.DataFrame()
    ind = _indicator(df, target, card) if target and target.name in df else None
    kept = []
    for cand in cands:
        try:
            result = run_query(conn, compile_sql(cand.sql, rows_clause(None, None, None)))
        except Exception:
            continue
        if result["row_count"] == 0:
            continue
        _facts(cand, result)
        parts = dict.fromkeys(WEIGHTS, 0.0)
        parts["coverage"] = coverage(card, cand.columns)
        if cand.kind == "target_rate" and ind is not None:
            parts["variance"] = eta_squared(ind, df[cand.x])
        elif cand.kind == "measure_by_dim":
            # η² of the measure by the category; halved when the file has a target, so the target's
            # own breakdowns come first.
            values = pd.to_numeric(df[cand.y], errors="coerce")
            parts["variance"] = eta_squared(values, df[cand.x]) * (0.5 if target else 1.0)
        elif cand.kind == "count_by_dim":
            parts["variance"] = 0.25 * unevenness([r[1] for r in result["rows"]])
        elif cand.kind == "kpi_measure":
            values = pd.to_numeric(df[cand.y], errors="coerce").dropna()
            parts["skew"] = min(1.0, abs(float(values.skew())) / 2) if len(values) > 2 else 0.0
            parts["outliers"] = outlier_share(values)
        elif cand.kind == "kpi_rate" and ind is not None:
            p = float(ind.mean())
            parts["variance"] = 0.5 * (1 - abs(2 * p - 1))  # a rate near 0 or 1 says little
        elif cand.kind == "trend":
            parts["trend"] = kendall_tau([r[1] for r in result["rows"]])
        elif cand.kind == "histogram":
            values = pd.to_numeric(df[cand.x], errors="coerce").dropna()
            parts["skew"] = min(1.0, abs(float(values.skew())) / 2) if len(values) > 2 else 0.0
            parts["outliers"] = outlier_share(values)
        elif cand.kind == "box":
            values = pd.to_numeric(df[cand.y], errors="coerce")
            parts["variance"] = eta_squared(values, df[cand.x]) * 0.5
            parts["outliers"] = outlier_share(values)
        elif cand.kind == "heatmap" and ind is not None:
            key = df[cand.x].astype("string") + " · " + df[cand.series].astype("string")
            parts["variance"] = eta_squared(ind, key) * 0.8  # most of it is already in the one-category bars
        elif cand.kind == "scatter":
            a, b = pd.to_numeric(df[cand.x], errors="coerce"), pd.to_numeric(df[cand.y], errors="coerce")
            ok = a.notna() & b.notna()
            r = float(a[ok].corr(b[ok])) if ok.sum() > 2 and a[ok].std() > 0 and b[ok].std() > 0 else 0.0
            parts["correlation"] = abs(r) if not math.isnan(r) else 0.0
        cand.parts = {k: round(float(0 if math.isnan(v) else v), 4) for k, v in parts.items()}
        cand.score = round(sum(WEIGHTS[k] * v for k, v in cand.parts.items()), 4)
        kept.append(cand)
    return sorted(kept, key=lambda c: -c.score)
