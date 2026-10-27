"""Fact sheets (TRD §6.4, §7.4 step 1): everything a story card may say about a widget, computed in
code from the widget's result on a version.

Each fact is `{value, format, label}` plus its provenance, which "How do you know?" shows and
`verify` re-checks:
- `sql` and `cell: [row, col]`: a cell of the widget's own query (no global filter);
- `sql` and `scalar: true`: a one-value query over the widget's rows;
- `from` and `formula`: derived from other facts (a ratio, a change) or from the result (a test).
Formats are `pct`, `int`, `num`, `text`, `x` (a ratio) and `p` (a p-value as text).
"""

import math
from dataclasses import dataclass

import duckdb

from sherlock.agent.compose import fmt, fmt_kind
from sherlock.rows.query import ident

SMALL_SAMPLE = 30
# A group with fewer rows than this is never named the highest or the lowest: live, two passengers with
# no port led the overview at 100% (live test 2026-10-26, finding 9). It stays in the chart and the tests.
MIN_GROUP = 10
MISSING = "missing"  # the NULL group's name, not "None"
DATED = ("DATE", "TIMESTAMP")


@dataclass
class Source:
    """What a widget's facts are computed from."""
    sql: str            # the widget's compiled query, no global filter
    rows_sql: str       # the WHERE clause of its rows ({{rows}} compiled)
    spec: dict
    title: str
    columns: list[dict]  # result columns [{name, type}]
    rows: list[list]


def _fmt(value, kind: str) -> str:
    if kind == "x":
        return f"{value:.1f}×" if isinstance(value, (int, float)) else str(value)
    if kind == "p":
        return str(value)
    return fmt(value, kind)


def fact(value, kind: str, label: str, **prov) -> dict:
    return {"value": value, "format": kind, "label": label, "formatted": _fmt(value, kind), **prov}


def _numeric(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(float(v))


def _value_col(src: Source) -> int | None:
    """The result column the chart plots: the view's `y` option, else the first numeric column after
    the first. A KPI shows its `value` option, else its first column, as the app's tile does (not the
    count `n` beside it)."""
    names = [c["name"] for c in src.columns]
    view = src.spec.get("view", {})
    y = (view.get("options") or {}).get("y") or (view.get("options") or {}).get("value")
    if y in names:
        return names.index(y)
    if view.get("type") == "kpi":
        return 0
    for i in range(1, len(names)):
        if any(_numeric(r[i]) for r in src.rows):
            return i
    return 0 if src.rows and _numeric(src.rows[0][0]) else None


def _kind_for(src: Source, col: int) -> str:
    name = src.columns[col]["name"]
    agg = (src.spec.get("scope", {}).get("columns") or {}).get("agg")
    fmt_opt = (src.spec.get("view", {}).get("options") or {}).get("format") or (src.spec.get("view", {}).get("options") or {}).get("label_format")
    sample = next((r[col] for r in src.rows if r[col] is not None), None)
    if (agg == "rate" or fmt_opt == "pct") and _numeric(sample) and 0 <= float(sample) <= 1:
        return "pct"
    return fmt_kind(sample, name)


def p_text(p: float) -> str:
    if p < 0.001:
        return "p<0.001"
    return f"p={p:.3f}" if p < 0.1 else f"p={p:.2f}"


def _scalar(conn: duckdb.DuckDBPyConnection, sql: str):
    row = conn.execute(sql).fetchone()
    return row[0] if row else None


def group_name(value) -> str:
    return MISSING if value is None else str(value)


def _leading_groups(tree) -> int | None:
    """How many leading SELECT columns are the query's GROUP BY keys (by expression, alias or ordinal),
    or None when the keys aren't the first columns."""
    from sqlglot import exp

    group = tree.args.get("group")
    keys = group.expressions if group else []
    sel = tree.expressions
    found = set()
    for g in keys:
        for i, s in enumerate(sel):
            if (isinstance(g, exp.Literal) and g.is_int and int(g.name) == i + 1) or g == s.unalias() \
                    or (isinstance(g, exp.Column) and not g.table and s.alias and g.name == s.alias):
                found.add(i)
                break
        else:
            return None
    return len(found) if found and found == set(range(len(found))) else None


def _row_sizes(conn: duckdb.DuckDBPyConnection, src: Source) -> list[int | None]:
    """The rows behind each result row: its `n` column, else a `COUNT(*)` added to the widget's grouped
    query, matched on the group keys. None where that can't be told (no GROUP BY, a UNION)."""
    names = [c["name"] for c in src.columns]
    if "n" in names:
        ni = names.index("n")
        return [int(r[ni]) if _numeric(r[ni]) else None for r in src.rows]
    unknown: list[int | None] = [None] * len(src.rows)
    import sqlglot
    from sqlglot import exp

    try:
        tree = sqlglot.parse_one(src.sql, read="duckdb")
    except sqlglot.errors.ParseError:
        return unknown
    k = _leading_groups(tree) if isinstance(tree, exp.Select) else None
    if not k:
        return unknown
    try:
        rows = conn.execute(tree.select("COUNT(*)", copy=True).sql(dialect="duckdb")).fetchall()
    except duckdb.Error:
        return unknown
    sizes = {tuple(group_name(v) for v in r[:k]): r[-1] for r in rows}
    return [sizes.get(tuple(group_name(v) for v in r[:k])) for r in src.rows]


def _rankable(pairs: list, sizes: list[int | None]) -> list:
    """The groups that may be named highest or lowest: those with `MIN_GROUP` rows or more (or an
    unknown size). When every group is that small, all of them (the small-sample note covers it)."""
    big = [p for p in pairs if sizes[p[0]] is None or sizes[p[0]] >= MIN_GROUP]
    return big or pairs


def compute(conn: duckdb.DuckDBPyConnection, src: Source) -> dict[str, dict]:
    """The facts for one widget. `conn` holds the version as `t`."""
    view = src.spec.get("view", {}).get("type", "table")
    if not src.rows:
        return {"rows": fact(0, "int", "rows in the result", sql=src.sql, formula="rows the query returned")}
    facts: dict[str, dict] = {}
    # Rows with the widget's columns filled: an average of fare is over the rows that have a fare.
    cols = src.spec.get("scope", {}).get("columns") or {}
    present = {r[0] for r in conn.execute("DESCRIBE t").fetchall()}
    filled = "".join(f" AND {ident(c)} IS NOT NULL" for c in dict.fromkeys(cols.get(k) for k in ("x", "series", "y"))
                     if c and c in present)
    n_sql = f"SELECT COUNT(*) FROM t WHERE {src.rows_sql}{filled}"
    facts["n"] = fact(_scalar(conn, n_sql), "int", "rows behind this widget", sql=n_sql, scalar=True)
    vc = _value_col(src)
    first_type = src.columns[0]["type"] if src.columns else ""
    if view == "kpi" or (len(src.rows) == 1 and vc is not None):
        col = vc if vc is not None else 0
        facts["value"] = fact(src.rows[0][col], _kind_for(src, col), src.title or src.columns[col]["name"],
                              sql=src.sql, cell=[0, col])
        return facts
    if vc is None:
        facts["rows"] = fact(len(src.rows), "int", "rows in the result", sql=src.sql, formula="rows the query returned")
        return facts
    kind = _kind_for(src, vc)
    vname = src.columns[vc]["name"]
    xname = src.columns[0]["name"]
    pairs = [(i, r[0], r[vc]) for i, r in enumerate(src.rows) if _numeric(r[vc])]
    if not pairs:
        return facts
    if first_type.startswith(DATED) and view in ("line", "area", "bar", "table"):
        _time(facts, src, pairs, vc, kind, vname)
    elif view in ("histogram",):
        _histogram(facts, conn, src)
    elif view == "scatter":
        _scatter(facts, conn, src)
    elif view == "box":
        _box(facts, conn, src)
    elif view == "heatmap":
        _heatmap(facts, conn, src, vc, kind)
    else:
        _categories(facts, conn, src, pairs, vc, kind, vname, xname)
    return facts


def _categories(facts, conn, src: Source, pairs, vc, kind, vname, xname) -> None:
    ranked = _rankable(pairs, _row_sizes(conn, src))
    top = max(ranked, key=lambda p: p[2])
    bottom = min(ranked, key=lambda p: p[2])
    facts["groups"] = fact(len(pairs), "int", f"{xname} groups shown", sql=src.sql, formula="rows the query returned")
    if len(ranked) < len(pairs):
        facts["small_groups"] = fact(len(pairs) - len(ranked), "int", f"{xname} groups too small to rank",
                                     **{"from": ["result"], "formula": f"groups with fewer than {MIN_GROUP} rows"})
    facts["top_group"] = fact(group_name(top[1]), "text", f"{xname} with the highest {vname}", sql=src.sql, cell=[top[0], 0])
    facts["top_value"] = fact(top[2], kind, f"{vname} for the top {xname}", sql=src.sql, cell=[top[0], vc])
    facts["bottom_group"] = fact(group_name(bottom[1]), "text", f"{xname} with the lowest {vname}", sql=src.sql, cell=[bottom[0], 0])
    facts["bottom_value"] = fact(bottom[2], kind, f"{vname} for the bottom {xname}", sql=src.sql, cell=[bottom[0], vc])
    if bottom[2] and bottom[2] > 0 and top[2] > 0:
        facts["ratio_top_bottom"] = fact(round(top[2] / bottom[2], 3), "x", "top value over bottom value",
                                         **{"from": ["top_value", "bottom_value"], "formula": "a / b"})
    names = [c["name"] for c in src.columns]
    agg = (src.spec.get("scope", {}).get("columns") or {}).get("agg")
    if "n" in names and vc != names.index("n"):
        ni = names.index("n")
        ns = [r[ni] for r in src.rows]
        if all(_numeric(v) for v in ns):
            if kind == "pct":
                pos = [round(r[vc] * r[ni]) for r in src.rows if _numeric(r[vc])]
                tot = [r[ni] for r in src.rows if _numeric(r[vc])]
                if sum(tot):
                    overall = sum(pos) / sum(tot)
                    facts["overall"] = fact(round(overall, 6), "pct", f"overall {vname}",
                                            **{"from": ["result"], "formula": "weighted by n over the groups"})
                _chi2(facts, pos, tot)
            elif agg in ("avg", "median", "sum") and len(pairs) >= 2:
                _kruskal(facts, conn, src, names)


def _chi2(facts, pos: list[int], tot: list[int]) -> None:
    from scipy.stats import chi2_contingency

    table = [[p, t - p] for p, t in zip(pos, tot) if t > 0]
    if len(table) < 2 or any(sum(col) == 0 for col in zip(*table)):
        return
    chi2, p, _, _ = chi2_contingency(table)
    n = sum(sum(r) for r in table)
    v = math.sqrt(chi2 / n) if n else 0.0
    facts["significance"] = fact(p_text(p), "p", "chance the gap is noise", method="chi2",
                                 **{"from": ["result"], "formula": "chi-squared test on the groups' counts"})
    facts["effect"] = fact(round(v, 3), "num", "strength of the link (Cramér's V, from none to perfect)",
                           **{"from": ["result"], "formula": "Cramér's V from the chi-squared test"})


def _kruskal(facts, conn, src: Source, names) -> None:
    from scipy.stats import kruskal

    cols = src.spec.get("scope", {}).get("columns") or {}
    x, y = cols.get("x"), cols.get("y")
    if not x or not y:
        return
    sql = f"SELECT {ident(x)}, {ident(y)} FROM t WHERE {src.rows_sql} AND {ident(x)} IS NOT NULL AND {ident(y)} IS NOT NULL"
    try:
        data = conn.execute(sql).fetchall()
    except duckdb.Error:
        return
    groups: dict = {}
    for k, v in data:
        if _numeric(v):
            groups.setdefault(k, []).append(float(v))
    samples = [g for g in groups.values() if len(g) >= 2]
    if len(samples) < 2:
        return
    try:
        _, p = kruskal(*samples)
    except ValueError:
        return
    facts["significance"] = fact(p_text(p), "p", "chance the differences are noise", method="kruskal", sql=sql,
                                 formula="Kruskal-Wallis test on the rows behind each group")


def _time(facts, src: Source, pairs, vc, kind, vname) -> None:
    from scipy.stats import kendalltau

    first, last = pairs[0], pairs[-1]
    peak = max(pairs, key=lambda p: p[2])
    facts["first_period"] = fact(str(first[1])[:10], "text", "first period", sql=src.sql, cell=[first[0], 0])
    facts["first_value"] = fact(first[2], kind, f"{vname} in the first period", sql=src.sql, cell=[first[0], vc])
    facts["last_period"] = fact(str(last[1])[:10], "text", "last period", sql=src.sql, cell=[last[0], 0])
    facts["last_value"] = fact(last[2], kind, f"{vname} in the last period", sql=src.sql, cell=[last[0], vc])
    facts["peak_period"] = fact(str(peak[1])[:10], "text", f"period with the highest {vname}", sql=src.sql, cell=[peak[0], 0])
    facts["peak_value"] = fact(peak[2], kind, f"highest {vname}", sql=src.sql, cell=[peak[0], vc])
    facts["periods"] = fact(len(pairs), "int", "periods shown", sql=src.sql, formula="rows the query returned")
    if first[2]:
        facts["change"] = fact(round((last[2] - first[2]) / abs(first[2]), 6), "pct", "change from first to last period",
                               **{"from": ["first_value", "last_value"], "formula": "(b - a) / |a|"})
    if len(pairs) >= 4:
        tau, p = kendalltau(range(len(pairs)), [v for _, _, v in pairs])
        direction = "flat" if p >= 0.05 or math.isnan(tau) else ("rising" if tau > 0 else "falling")
        facts["trend"] = fact(direction, "text", "direction of the trend", method="kendall",
                              **{"from": ["result"], "formula": "Kendall's tau over the periods, significant at 0.05"})
        facts["trend_significance"] = fact(p_text(p if not math.isnan(p) else 1.0), "p", "chance the trend is noise",
                                           method="kendall", **{"from": ["result"], "formula": "Kendall's tau test"})


def _histogram(facts, conn, src: Source) -> None:
    y = (src.spec.get("scope", {}).get("columns") or {}).get("x") or (src.spec.get("scope", {}).get("columns") or {}).get("y")
    if not y:
        return
    q = ident(y)
    base = f"FROM t WHERE {src.rows_sql} AND {q} IS NOT NULL"
    for key, expr, label in (("median", f"MEDIAN({q})", f"median {y}"), ("mean", f"AVG({q})", f"average {y}"),
                             ("min", f"MIN({q})", f"lowest {y}"), ("max", f"MAX({q})", f"highest {y}")):
        sql = f"SELECT {expr} {base}"
        v = _scalar(conn, sql)
        if v is not None:
            facts[key] = fact(float(v), "num", label, sql=sql, scalar=True)
    sql = (f"SELECT AVG(CASE WHEN {q} < q1 - 1.5 * (q3 - q1) OR {q} > q3 + 1.5 * (q3 - q1) THEN 1 ELSE 0 END) "
           f"FROM (SELECT {q}, QUANTILE_CONT({q}, 0.25) OVER () AS q1, QUANTILE_CONT({q}, 0.75) OVER () AS q3 {base})")
    v = _scalar(conn, sql)
    if v is not None:
        facts["outlier_share"] = fact(float(v), "pct", f"share of {y} values far from the middle", sql=sql, scalar=True)


def _scatter(facts, conn, src: Source) -> None:
    cols = src.spec.get("scope", {}).get("columns") or {}
    x, y = cols.get("x"), cols.get("y")
    if not x or not y:
        return
    sql = f"SELECT CORR({ident(x)}, {ident(y)}) FROM t WHERE {src.rows_sql}"
    r = _scalar(conn, sql)
    if r is None or not math.isfinite(r):
        return
    facts["correlation"] = fact(round(float(r), 4), "num", f"correlation of {x} and {y}", sql=sql, scalar=True)
    facts["direction"] = fact("positive" if r > 0 else "negative", "text", "direction of the link",
                              **{"from": ["correlation"], "formula": "sign of the correlation"})


def _box(facts, conn, src: Source) -> None:
    names = [c["name"] for c in src.columns]
    if "median" not in names:
        return
    mi = names.index("median")
    pairs = [(i, r[0], r[mi]) for i, r in enumerate(src.rows) if _numeric(r[mi])]
    if not pairs:
        return
    ranked = _rankable(pairs, _row_sizes(conn, src))
    top, bottom = max(ranked, key=lambda p: p[2]), min(ranked, key=lambda p: p[2])
    k = fmt_kind(top[2], "median")
    facts["top_group"] = fact(group_name(top[1]), "text", "group with the highest median", sql=src.sql, cell=[top[0], 0])
    facts["top_median"] = fact(top[2], k, "highest median", sql=src.sql, cell=[top[0], mi])
    facts["bottom_group"] = fact(group_name(bottom[1]), "text", "group with the lowest median", sql=src.sql, cell=[bottom[0], 0])
    facts["bottom_median"] = fact(bottom[2], k, "lowest median", sql=src.sql, cell=[bottom[0], mi])


def _heatmap(facts, conn, src: Source, vc, kind) -> None:
    pairs = [(i, r) for i, r in enumerate(src.rows) if _numeric(r[vc])]
    if not pairs or len(src.columns) < 3:
        return
    i, r = max(_rankable(pairs, _row_sizes(conn, src)), key=lambda p: p[1][vc])
    facts["max_x"] = fact(group_name(r[0]), "text", f"{src.columns[0]['name']} of the highest cell", sql=src.sql, cell=[i, 0])
    facts["max_y"] = fact(group_name(r[1]), "text", f"{src.columns[1]['name']} of the highest cell", sql=src.sql, cell=[i, 1])
    facts["max_value"] = fact(r[vc], kind, f"highest {src.columns[vc]['name']}", sql=src.sql, cell=[i, vc])


# --- verification (TRD §7.4 step 4) -------------------------------------------------------------

def _close(a, b) -> bool:
    if _numeric(a) and _numeric(b):
        a, b = float(a), float(b)
        return a == b or abs(a - b) <= 0.005 * max(abs(a), abs(b))
    return str(a) == str(b)


def verify(conn: duckdb.DuckDBPyConnection, facts: dict[str, dict], keys: list[str]) -> list[str]:
    """Re-run each named fact's query (or recompute a derived fact) on the version; returns the keys
    whose value no longer matches (0.5% relative tolerance)."""
    failed = []
    results: dict[str, list] = {}
    for key in keys:
        f = facts.get(key)
        if f is None:
            failed.append(key)
            continue
        try:
            if f.get("scalar"):
                ok = _close(_scalar(conn, f["sql"]), f["value"])
            elif f.get("cell") and f.get("sql"):
                rows = results.get(f["sql"])
                if rows is None:
                    rows = results[f["sql"]] = conn.execute(f["sql"]).fetchall()
                r, c = f["cell"]
                actual = rows[r][c] if r < len(rows) else None
                if actual is None and f.get("format") == "text":
                    actual = group_name(actual)  # the NULL group, named "missing"
                ok = r < len(rows) and _close(actual, f["value"])
            elif f.get("formula") == "a / b":
                a, b = (facts[k]["value"] for k in f["from"])
                ok = bool(b) and _close(a / b, f["value"])
            elif f.get("formula") == "(b - a) / |a|":
                a, b = (facts[k]["value"] for k in f["from"])
                ok = bool(a) and _close((b - a) / abs(a), f["value"])
            else:
                ok = True  # tests and labels from the result: recomputed with the sheet itself
        except (duckdb.Error, KeyError, TypeError, ZeroDivisionError):
            ok = False
        if not ok:
            failed.append(key)
    return failed


def depends_on(spec: dict, sql: str, columns: list[str] | None = None) -> list[str]:
    """The data columns a widget reads: its scope's columns and every column its query names. A column
    qualified by an alias of `t` (`FROM t AS a`, `a.fare`) counts, and with `columns` (the version's) a
    `*` or `a.*` reads every one of them; `COUNT(*)` reads none."""
    import sqlglot
    from sqlglot import exp

    cols = set()
    sc = spec.get("scope", {}).get("columns") or {}
    for k in ("x", "y", "series", "target"):
        if sc.get(k):
            cols.add(sc[k])
    cols.update(sc.get("features") or [])
    try:
        tree = sqlglot.parse_one(sql, read="duckdb")
    except sqlglot.errors.ParseError:
        tree = None
    if tree is not None:
        names = {"", "t"} | {tb.alias for tb in tree.find_all(exp.Table) if tb.name == "t" and tb.alias}
        for c in tree.find_all(exp.Column):
            if c.table in names and not isinstance(c.this, exp.Star):  # `b.lo` in a histogram is its own CTE's
                cols.add(c.name)
        if columns is not None and _reads_every_column(tree, names):
            cols.update(columns)
    return sorted(c for c in cols if c not in ("_row_id", "_quarantine_reason"))


def _reads_every_column(tree, names: set[str]) -> bool:
    """A bare `*` (with or without EXCLUDE) or `a.*` of `t`, outside an aggregate like `COUNT(*)`."""
    from sqlglot import exp

    for star in tree.find_all(exp.Star):
        parent = star.parent
        if isinstance(parent, exp.Column):
            if parent.table not in names:
                continue
            parent = parent.parent
        if isinstance(parent, exp.AggFunc):
            continue
        return True
    return False


def small_sample(facts: dict) -> bool:
    n = facts.get("n", {}).get("value")
    return isinstance(n, int) and n < SMALL_SAMPLE

