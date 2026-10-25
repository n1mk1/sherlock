"""Row pages for the CSV tab (TRD §4.3): paging, sort, filter, quick views, selection.

Sorting and filtering change the view only (PRD CSV-8). Every column name is checked against the
version's columns and quoted; every value is a bound parameter, so nothing from the request is
pasted into SQL.
"""

import datetime as dt
import decimal
import json
import math
from dataclasses import dataclass

import duckdb

from sherlock.errors import ApiError

SYSTEM = ("_row_id", "_quarantine_reason")
OPS = ("eq", "neq", "in", "gt", "gte", "lt", "lte", "contains", "empty", "notempty")
VIEWS = ("all", "changed", "flagged", "missing")
MAX_LIMIT = 500


def ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def invalid(message: str) -> ApiError:
    return ApiError(422, "invalid", message)


@dataclass
class Where:
    sql: list[str]
    params: list

    def add(self, sql: str, *params) -> None:
        self.sql.append(sql)
        self.params.extend(params)

    def clause(self) -> str:
        return " AND ".join(self.sql) if self.sql else "TRUE"


def parse_sort(raw: str | None, columns: list[str]) -> str:
    if not raw:
        return "_row_id"
    parts = []
    for item in raw.split(","):
        name, _, direction = item.strip().rpartition(":")
        if not name:
            name, direction = direction, "asc"
        direction = direction.lower()
        if name not in columns or direction not in ("asc", "desc"):
            raise invalid(f"sort: unknown column or direction in {item!r}")
        parts.append(f"{ident(name)} {direction.upper()} NULLS LAST")
    return ", ".join(parts + ["_row_id"])


def _as_text(column: str) -> str:
    return f"CAST({ident(column)} AS VARCHAR)"


def apply_filter(where: Where, raw: str | None, types: dict[str, str]) -> None:
    """Filter JSON: `{"and": [{"col", "op", "value"}]}`. Comparisons run on the column's type."""
    if not raw:
        return
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError:
        raise invalid("filter: not valid JSON") from None
    clauses = spec.get("and") if isinstance(spec, dict) else None
    if not isinstance(clauses, list):
        raise invalid('filter: expected {"and": [...]}')
    for c in clauses:
        if not isinstance(c, dict) or c.get("col") not in types or c.get("op") not in OPS:
            raise invalid(f"filter: unknown column or operator in {json.dumps(c)[:80]}")
        col, op, value = c["col"], c["op"], c.get("value")
        q, t = ident(col), types[col]
        if op == "empty":
            where.add(f"({q} IS NULL OR trim({_as_text(col)}) = '')")
        elif op == "notempty":
            where.add(f"({q} IS NOT NULL AND trim({_as_text(col)}) != '')")
        elif op == "contains":
            text = "" if value is None else str(value)
            needle = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            where.add(f"{_as_text(col)} ILIKE ? ESCAPE '\\'", f"%{needle}%")
        elif op == "in":
            if not isinstance(value, list) or not value:
                raise invalid("filter: `in` needs a non-empty list")
            where.add(f"{_as_text(col)} IN ({', '.join('?' for _ in value)})", *[str(v) for v in value])
        else:
            sql_op = {"eq": "=", "neq": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[op]
            where.add(f"{q} {sql_op} TRY_CAST(? AS {t})", None if value is None else str(value))


def json_value(value):
    """A DuckDB value as JSON: dates as ISO strings, NaN as null."""
    if value is None:
        return None
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (dt.date, dt.datetime, dt.time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    return value


def describe(conn: duckdb.DuckDBPyConnection) -> dict[str, str]:
    return {r[0]: str(r[1]) for r in conn.execute("DESCRIBE t").fetchall()}


def page(
    conn: duckdb.DuckDBPyConnection,
    where: Where,
    order_by: str,
    offset: int,
    limit: int,
) -> tuple[int, list[str], list[tuple]]:
    """(total, column names, rows) for the filtered, sorted page."""
    clause = where.clause()
    total = conn.execute(f"SELECT count(*) FROM t WHERE {clause}", where.params).fetchone()[0]
    cur = conn.execute(
        f"SELECT * FROM t WHERE {clause} ORDER BY {order_by} LIMIT ? OFFSET ?", [*where.params, limit, offset]
    )
    names = [d[0] for d in cur.description]
    return total, names, cur.fetchall()
