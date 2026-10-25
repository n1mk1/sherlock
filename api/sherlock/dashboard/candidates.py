"""Candidate widgets from the DataCard's roles (TRD §7.3 step 1), as SQL widget specs.

Until the custom visx charts land (Implementation Plan D6.5) candidates use only the bar, line, area,
KPI and table views. A dimension is charted only with 2–12 categories. Wide files use the 30 most
informative columns. Nothing here depends on a particular dataset: everything comes from types,
roles and distinct counts.
"""

import re
from dataclasses import dataclass, field

from sherlock.rows.query import ident

MAX_CANDIDATES = 60
MAX_COLUMNS = 30
MAX_CATEGORIES = 12
SUM_NAMES = re.compile(r"(revenue|sales|amount|total|cost|profit|spend|units|quantity|qty|count|volume)", re.I)
POSITIVE = ("1", "true", "yes", "y", "t")


@dataclass
class Candidate:
    key: str
    kind: str  # kpi_rows | kpi_rate | kpi_measure | target_rate | measure_by_dim | count_by_dim | trend | top_table
    view: str
    sql: str
    title: str
    columns: list[str]
    x: str | None = None
    y: str | None = None
    agg: str | None = None
    options: dict = field(default_factory=dict)
    score: float = 0.0
    parts: dict = field(default_factory=dict)
    point: dict | None = None
    facts: dict = field(default_factory=dict)  # the top and bottom elements, computed in code
    series: str | None = None  # a second category (heatmaps)

    def spec(self) -> dict:
        return {
            "scope": {"columns": {"x": self.x, "y": self.y, "agg": self.agg, "series": self.series, "target": None,
                                  "features": None, "exclude": []},
                      "rows": {"predicate": None, "selection_id": None, "inherit_global_filters": True}},
            "op": {"type": "sql", "sql": self.sql},
            "view": {"type": self.view, "from": "result", "options": self.options},
        }


@dataclass
class Target:
    name: str
    indicator: str  # SQL for 1.0 / 0.0 per row
    positive: str   # what the rate counts, for titles
    value: float | None = None  # the positive value of a numeric target not coded 0/1


def binary_target(card: dict) -> Target | None:
    """The first target-like column with exactly two values, and how to count its positive value.
    Only a bool or a 0/1 number is averaged as it is; a number coded otherwise (1/2, say) counts its
    positive value like a text target, so a rate never passes 100%."""
    for name in card.get("target_candidates") or []:
        col = next((c for c in card["columns"] if c["name"] == name), None)
        if col is None or col["distinct"] != 2:
            continue
        q = ident(name)
        if col["type"] == "bool":
            return Target(name, f"CAST({q} AS DOUBLE)", name)
        if col["type"] in ("int", "float"):
            lo, hi = (col.get("stats") or {}).get("min"), (col.get("stats") or {}).get("max")
            if lo is None or hi is None or (lo, hi) == (0, 1):
                return Target(name, f"CAST({q} AS DOUBLE)", name)
            pos = next((v for v in (lo, hi) if str(v) in POSITIVE), hi)
            return Target(name, f"CASE WHEN {q} IS NULL THEN NULL WHEN {q} = {pos} THEN 1.0 ELSE 0.0 END",
                          f"{name} = {pos}", float(pos))
        values = [str(v["value"]) for v in (col.get("top_values") or [])]
        if len(values) == 2:
            pos = next((v for v in values if v.strip().lower() in POSITIVE), min(values, key=lambda v: _count(col, v)))
            lit = "'" + pos.replace("'", "''") + "'"
            return Target(name, f"CASE WHEN CAST({q} AS VARCHAR) = {lit} THEN 1.0 ELSE 0.0 END", f"{name} = {pos}")
    return None


def _count(col: dict, value: str) -> int:
    return next((v["count"] for v in col.get("top_values") or [] if str(v["value"]) == value), 0)


def chartable_dims(card: dict, exclude: set[str]) -> list[dict]:
    return [c for c in card["columns"]
            if c["role"] in ("dimension", "target_like") and 2 <= (c["distinct"] or 0) <= MAX_CATEGORIES
            and c["name"] not in exclude]


def measures(card: dict) -> list[dict]:
    return [c for c in card["columns"] if c["role"] == "measure" and c["type"] in ("int", "float")]


def _agg_for(col: dict) -> str:
    return "sum" if SUM_NAMES.search(col["name"]) else "avg"


def _agg_sql(agg: str, q: str) -> str:
    return {"sum": f"SUM({q})", "avg": f"AVG({q})"}[agg]


def _word(agg: str) -> str:
    return "Total" if agg == "sum" else "Average"


def generate(card: dict, keep: list[str] | None = None) -> list[Candidate]:
    """Up to 60 candidates over the columns in `keep` (default: all of them)."""
    keep_set = set(keep) if keep is not None else {c["name"] for c in card["columns"]}
    card = {**card, "columns": [c for c in card["columns"] if c["name"] in keep_set and c["role"] != "empty"]}
    target = binary_target(card)
    target_name = target.name if target else None
    dims = chartable_dims(card, {target_name} if target_name else set())
    meas = measures(card)
    times = [c for c in card["columns"] if c["role"] == "time" and c["type"] in ("date", "datetime")]
    ids = [c for c in card["columns"] if c["role"] == "id"]
    rows = "WHERE {{rows}}"
    out: list[Candidate] = []

    out.append(Candidate("kpi:rows", "kpi_rows", "kpi", f"SELECT COUNT(*) AS n_rows FROM t {rows}", "Rows", [],
                         agg="count", options={"value": "n_rows", "format": "int"}))
    if target:
        q = ident(target.name)
        out.append(Candidate(
            f"kpi:rate:{target.name}", "kpi_rate", "kpi",
            f"SELECT AVG({target.indicator}) AS rate, COUNT(*) AS n FROM t {rows} AND {q} IS NOT NULL",
            f"Rate of {target.positive}", [target.name], y=target.name, agg="rate",
            options={"value": "rate", "format": "pct", "sub": "n"}))
    for m in meas:
        agg, q = _agg_for(m), ident(m["name"])
        out.append(Candidate(
            f"kpi:{agg}:{m['name']}", "kpi_measure", "kpi",
            f"SELECT {_agg_sql(agg, q)} AS value, COUNT({q}) AS n FROM t {rows}",
            f"{_word(agg)} {m['name']}", [m["name"]], y=m["name"], agg=agg,
            options={"value": "value", "format": "num", "sub": "n"}))

    for d in dims:
        qd = ident(d["name"])
        order = "1" if d["type"] in ("int", "float", "bool") else "2 DESC, 1"
        if target:
            out.append(Candidate(
                f"bar:rate:{target.name}:{d['name']}", "target_rate", "bar",
                f"SELECT {qd}, AVG({target.indicator}) AS rate, COUNT(*) AS n FROM t {rows} "
                f"AND {qd} IS NOT NULL AND {ident(target.name)} IS NOT NULL GROUP BY 1 ORDER BY {order}",
                f"Rate of {target.positive} by {d['name']}", [target.name, d["name"]], x=d["name"], y=target.name,
                agg="rate", options={"x": d["name"], "y": "rate", "label_format": "pct"}))
        for m in meas:
            agg, qm = _agg_for(m), ident(m["name"])
            alias = f"{agg}_{m['name']}"
            out.append(Candidate(
                f"bar:{agg}:{m['name']}:{d['name']}", "measure_by_dim", "bar",
                f"SELECT {qd}, {_agg_sql(agg, qm)} AS {ident(alias)}, COUNT({qm}) AS n FROM t {rows} "
                f"AND {qd} IS NOT NULL GROUP BY 1 ORDER BY {order}",
                f"{_word(agg)} {m['name']} by {d['name']}", [m["name"], d["name"]], x=d["name"], y=m["name"],
                agg=agg, options={"x": d["name"], "y": alias}))
        view = "ring" if d["distinct"] <= 5 else "bar"
        out.append(Candidate(
            f"{view}:count:{d['name']}", "count_by_dim", view,
            f"SELECT {qd}, COUNT(*) AS n FROM t {rows} AND {qd} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC, 1",
            f"Rows by {d['name']}", [d["name"]], x=d["name"], agg="count", options={"x": d["name"], "y": "n"}))

    for tcol in times:
        qt = ident(tcol["name"])
        span_days = _span_days(tcol)
        unit = "month" if span_days is None or span_days > 120 else ("week" if span_days > 31 else "day")
        bucket = f"date_trunc('{unit}', {qt})"
        out.append(Candidate(
            f"area:count:{tcol['name']}", "trend", "area",
            f"SELECT {bucket} AS period, COUNT(*) AS n FROM t {rows} AND {qt} IS NOT NULL GROUP BY 1 ORDER BY 1",
            f"Rows by {unit}", [tcol["name"]], x=tcol["name"], agg="count", options={"x": "period", "y": "n"}))
        for m in meas:
            agg, qm = _agg_for(m), ident(m["name"])
            alias = f"{agg}_{m['name']}"
            out.append(Candidate(
                f"line:{agg}:{m['name']}:{tcol['name']}", "trend", "line",
                f"SELECT {bucket} AS period, {_agg_sql(agg, qm)} AS {ident(alias)} FROM t {rows} "
                f"AND {qt} IS NOT NULL GROUP BY 1 ORDER BY 1",
                f"{_word(agg)} {m['name']} by {unit}", [m["name"], tcol["name"]], x=tcol["name"], y=m["name"],
                agg=agg, options={"x": "period", "y": alias}))
        if target:
            out.append(Candidate(
                f"line:rate:{target.name}:{tcol['name']}", "trend", "line",
                f"SELECT {bucket} AS period, AVG({target.indicator}) AS rate FROM t {rows} "
                f"AND {qt} IS NOT NULL AND {ident(target.name)} IS NOT NULL GROUP BY 1 ORDER BY 1",
                f"Rate of {target.positive} by {unit}", [target.name, tcol["name"]], x=tcol["name"], y=target.name,
                agg="rate", options={"x": "period", "y": "rate", "label_format": "pct"}))

    out += _distributions(dims, meas, target, rows)

    if ids and meas:
        idc, m = ids[0], meas[0]
        qi, qm = ident(idc["name"]), ident(m["name"])
        out.append(Candidate(
            f"table:top:{idc['name']}:{m['name']}", "top_table", "table",
            f"SELECT {qi}, {qm} FROM t {rows} AND {qm} IS NOT NULL ORDER BY 2 DESC, 1 LIMIT 10",
            f"Top {idc['name']} by {m['name']}", [idc["name"], m["name"]], x=idc["name"], y=m["name"]))
    elif not meas:
        # No numbers: the most common values of each text column (App Flow §18, all-text files).
        for c in [c for c in card["columns"] if c["role"] in ("free_text", "dimension") and c not in dims][:3]:
            qc = ident(c["name"])
            out.append(Candidate(
                f"table:values:{c['name']}", "top_table", "table",
                f"SELECT {qc}, COUNT(*) AS n FROM t {rows} AND {qc} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 10",
                f"Most common {c['name']}", [c["name"]], x=c["name"], agg="count"))
    return out[:MAX_CANDIDATES]


def _distributions(dims: list[dict], meas: list[dict], target: Target | None, rows: str) -> list[Candidate]:
    """The custom charts (Implementation Plan D6.5): a histogram per measure, a box plot of a measure
    by a category, the target's rate by two categories as a heatmap, and scatters of measure pairs
    (scoring keeps the most correlated)."""
    out: list[Candidate] = []
    for m in meas[:4]:
        q = ident(m["name"])
        out.append(Candidate(
            f"histogram:{m['name']}", "histogram", "histogram",
            f"WITH b AS (SELECT MIN({q}) AS lo, (MAX({q}) - MIN({q})) / 20 AS w FROM t {rows} AND {q} IS NOT NULL) "
            f"SELECT b.lo + b.w * COALESCE(LEAST(FLOOR(({q} - b.lo) / NULLIF(b.w, 0)), 19), 0) AS bin_start, "
            f"COUNT(*) AS n FROM t, b {rows} AND {q} IS NOT NULL GROUP BY 1 ORDER BY 1",
            f"Distribution of {m['name']}", [m["name"]], x=m["name"], agg="count", options={"x": "bin_start", "y": "n"}))
    small = [d for d in dims if (d["distinct"] or 0) <= 8]
    for d in small[:2]:
        for m in meas[:2]:
            qd, qm = ident(d["name"]), ident(m["name"])
            out.append(Candidate(
                f"box:{m['name']}:{d['name']}", "box", "box",
                f"SELECT {qd}, MIN({qm}) AS min, QUANTILE_CONT({qm}, 0.25) AS q1, MEDIAN({qm}) AS median, "
                f"QUANTILE_CONT({qm}, 0.75) AS q3, MAX({qm}) AS max, COUNT(*) AS n FROM t {rows} "
                f"AND {qd} IS NOT NULL AND {qm} IS NOT NULL GROUP BY 1 ORDER BY 1",
                f"{m['name']} by {d['name']}", [m["name"], d["name"]], x=d["name"], y=m["name"], agg="median",
                options={"x": d["name"], "y": "median"}))
    if target:
        pairs = [(a, b) for i, a in enumerate(small[:3]) for b in small[i + 1:3]]
        for a, b in pairs:
            qa, qb = ident(a["name"]), ident(b["name"])
            out.append(Candidate(
                f"heatmap:{target.name}:{a['name']}:{b['name']}", "heatmap", "heatmap",
                f"SELECT {qa}, {qb}, AVG({target.indicator}) AS rate, COUNT(*) AS n FROM t {rows} AND {qa} IS NOT NULL "
                f"AND {qb} IS NOT NULL AND {ident(target.name)} IS NOT NULL GROUP BY 1, 2 ORDER BY 1, 2",
                f"Rate of {target.positive} by {a['name']} and {b['name']}", [target.name, a["name"], b["name"]],
                x=a["name"], y=target.name, agg="rate",
                options={"x": a["name"], "series": b["name"], "y": "rate", "label_format": "pct"}))
            out[-1].series = b["name"]
    for i, a in enumerate(meas[:4]):
        for b in meas[i + 1:4]:
            qa, qb = ident(a["name"]), ident(b["name"])
            out.append(Candidate(
                f"scatter:{a['name']}:{b['name']}", "scatter", "scatter",
                f"SELECT {qa}, {qb} FROM t {rows} AND {qa} IS NOT NULL AND {qb} IS NOT NULL ORDER BY _row_id LIMIT 2000",
                f"{b['name']} against {a['name']}", [a["name"], b["name"]], x=a["name"], y=b["name"],
                options={"x": a["name"], "y": b["name"]}))
    return out


def _span_days(col: dict) -> float | None:
    stats = col.get("stats") or {}
    try:
        from datetime import date

        lo, hi = date.fromisoformat(str(stats["min"])[:10]), date.fromisoformat(str(stats["max"])[:10])
        return (hi - lo).days
    except (KeyError, ValueError, TypeError):
        return None
