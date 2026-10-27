"""SQL compile and validation for chat queries and ML scopes (TRD §6.3, §15).

A query names the table `t` and says where its rows go with `{{rows}}`, which compiles to
`_quarantine_reason IS NULL AND (<row predicate>)`, ANDed with the selection and any filter. Everything is rendered as literal SQL (values quoted here, column
names checked against the version), so the SQL shown under "How do you know?" is exactly what ran
and runs the same in the exported notebook. Only one `SELECT` over `t` passes `sqlglot`; a
`LIMIT 2000` is appended when there is none.
"""

import json
import math
import re

import sqlglot
from sqlglot import exp

from sherlock.errors import ApiError
from sherlock.rows.query import OPS, SYSTEM, ident

ROWS_TOKEN = "{{rows}}"
ROWS_MARK = "__sherlock_rows__"  # stands in for `{{rows}}` while its placement is checked
MAX_RESULT_ROWS = 2000
NUMERIC = re.compile(r"^(TINYINT|SMALLINT|INTEGER|BIGINT|HUGEINT|UTINYINT|USMALLINT|UINTEGER|UBIGINT|FLOAT|DOUBLE|REAL|DECIMAL.*)$")
# Statement kinds that never belong in a query, wherever they appear in the tree.
FORBIDDEN = (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create, exp.Alter, exp.Command, exp.Copy,
             exp.Set, exp.Pragma, exp.Use, exp.Merge, exp.TruncateTable)


class SqlError(ApiError):
    """A query that can't run: `422 invalid` with a plain-language reason."""

    def __init__(self, message: str) -> None:
        super().__init__(422, "invalid", message)


def literal(value) -> str:
    """A Python value as a SQL literal."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SqlError("Filter values must be finite numbers.")
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def _typed(value, column_type: str) -> str:
    """A filter value as a literal of its column's type: `3` for a number column, `'3'` for text."""
    if value is None:
        return "NULL"
    if NUMERIC.match(column_type):
        if isinstance(value, bool):
            return str(int(value))
        if isinstance(value, (int, float)):
            return literal(value)
        try:
            number = float(str(value))
        except ValueError:
            return f"TRY_CAST({literal(str(value))} AS {column_type})"
        return literal(int(number)) if number.is_integer() and "INT" in column_type else literal(number)
    if column_type == "BOOLEAN":
        if isinstance(value, bool):
            return literal(value)
        text = str(value).strip().lower()
        if text in ("true", "false"):
            return text.upper()
    return literal(value if isinstance(value, str) else str(value))


def parse_filter(raw: str | dict | None) -> list[dict]:
    """The global filter, `{"and": [{col, op, value}]}` as in the rows API (TRD §4.3), as a list."""
    if raw in (None, "", {}):
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raise SqlError("filters: not valid JSON") from None
    clauses = raw.get("and") if isinstance(raw, dict) else None
    if not isinstance(clauses, list):
        raise SqlError('filters: expected {"and": [...]}')
    for c in clauses:
        if not isinstance(c, dict) or not isinstance(c.get("col"), str) or c.get("op") not in OPS:
            raise SqlError(f"filters: unknown column or operator in {json.dumps(c)[:80]}")
    return clauses


def filter_sql(clauses: list[dict], types: dict[str, str]) -> str | None:
    """Literal SQL for the filter clauses; a clause on a column this version lacks is an error."""
    parts = []
    for c in clauses:
        col, op, value = c["col"], c["op"], c.get("value")
        if col not in types:
            raise SqlError(f"filters: unknown column {col!r}")
        q, t, text = ident(col), types[col], f"CAST({ident(col)} AS VARCHAR)"
        if op == "empty":
            parts.append(f"({q} IS NULL OR trim({text}) = '')")
        elif op == "notempty":
            parts.append(f"({q} IS NOT NULL AND trim({text}) != '')")
        elif op == "contains":
            # A plain substring, as in the rows API: `%`, `_` and `\` in the value match themselves.
            needle = str(value).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            parts.append(f"{text} ILIKE {literal('%' + needle + '%')} ESCAPE '\\'")
        elif op == "in":
            if not isinstance(value, list) or not value:
                raise SqlError("filters: `in` needs a non-empty list")
            parts.append(f"{q} IN ({', '.join(_typed(v, t) for v in value)})")
        elif value is None:
            parts.append(f"{q} IS NULL" if op == "eq" else f"{q} IS NOT NULL")
        else:
            sql_op = {"eq": "=", "neq": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[op]
            parts.append(f"{q} {sql_op} {_typed(value, t)}")
    return " AND ".join(parts) if parts else None


def _parse_one(sql: str) -> exp.Expression:
    try:
        statements = [s for s in sqlglot.parse(sql, read="duckdb") if s is not None]
    except sqlglot.errors.SqlglotError as exc:
        first = str(exc).strip().splitlines()[0] if str(exc).strip() else "syntax error"
        raise SqlError(f"The query doesn't parse: {first[:200]}") from None
    if len(statements) != 1:
        raise SqlError("A query is exactly one statement.")
    return statements[0]


def _check_tree(root: exp.Expression) -> None:
    if not isinstance(root, exp.Query):
        raise SqlError("Only SELECT queries are allowed.")
    ctes = {c.alias_or_name for c in root.find_all(exp.CTE)}
    for node in root.walk():
        if isinstance(node, FORBIDDEN):
            raise SqlError("Only SELECT queries are allowed.")
        if isinstance(node, exp.Table):
            name = node.this
            if not isinstance(name, exp.Identifier) or node.args.get("db") or node.args.get("catalog") or (
                    name.name != "t" and name.name not in ctes):
                raise SqlError("Queries can only read the table t.")
        if isinstance(node, exp.Func):
            fname = (node.sql_name() if not isinstance(node, exp.Anonymous) else node.name).lower()
            if fname.startswith(("read_", "glob", "parquet_", "sniff_")) or fname in ("query", "query_table"):
                raise SqlError("Queries can only read the table t.")


def validate_select(sql: str) -> str:
    """Check one compiled query and append `LIMIT 2000` when it has no limit. Returns the SQL to run."""
    body = sql.strip().rstrip(";").strip()
    if not body:
        raise SqlError("The query is empty.")
    root = _parse_one(body)
    _check_tree(root)
    if root.args.get("limit") is None:
        body = f"{body}\nLIMIT {MAX_RESULT_ROWS}"
    return body


def validate_predicate(predicate: str, columns: list[str]) -> str:
    """A row predicate (a `WHERE` fragment over `t`): no subqueries, only known columns."""
    text = predicate.strip()
    if not text:
        raise SqlError("The row predicate is empty.")
    root = _parse_one(f"SELECT 1 FROM t WHERE ({text})")
    _check_tree(root)
    where = root.args.get("where")
    if where is None or list(where.find_all(exp.Select)) or list(where.find_all(exp.Subquery)):
        raise SqlError("A row predicate can't contain a query.")
    if not isinstance(where.this, exp.Paren):
        # `a = 1) OR (1 = 1` closes the parentheses it's wrapped in and would OR past the
        # quarantine exclusion and the global filter.
        raise SqlError("The row predicate has unbalanced parentheses.")
    known = set(columns) | set(SYSTEM)
    for col in where.find_all(exp.Column):
        if col.name not in known:
            raise SqlError(f"Unknown column {col.name!r} in the row predicate.")
    return text


def rows_clause(predicate: str | None, selection: str | None, global_filter: str | None) -> str:
    """What `{{rows}}` becomes: the quarantine exclusion and the row predicate, then the selection and
    the global filter when they apply."""
    clause = f"_quarantine_reason IS NULL AND ({predicate or '1=1'})"
    if selection:
        clause += f" AND ({selection})"
    if global_filter:
        clause += f" AND ({global_filter})"
    return clause


def check_rows_placement(sql: str) -> None:
    """`{{rows}}` must be ANDed into the `WHERE` of every `SELECT` that reads `t`. Otherwise an `OR`
    (`WHERE {{rows}} OR x`), a `NOT` or a second read of `t` without it brings back quarantined and
    filtered-out rows."""
    root = _parse_one(sql.replace(ROWS_TOKEN, ROWS_MARK))
    marks = [c for c in root.find_all(exp.Column) if c.name == ROWS_MARK and not c.table]
    for mark in marks:
        node = mark
        while not isinstance(node.parent, exp.Where):
            if not isinstance(node.parent, (exp.And, exp.Paren)):
                raise SqlError("{{rows}} must be ANDed into the WHERE clause, as in WHERE {{rows}} AND ….")
            node = node.parent
    guarded = {id(m.find_ancestor(exp.Select)) for m in marks}
    for select in root.find_all(exp.Select):
        reads_t = any(tb.name == "t" and tb.find_ancestor(exp.Select) is select for tb in select.find_all(exp.Table))
        if reads_t and id(select) not in guarded:
            raise SqlError("Every SELECT that reads t must filter its rows with WHERE {{rows}}.")


def compile_sql(sql: str, rows: str) -> str:
    """Substitute `{{rows}}` and validate. SQL without `{{rows}}`, or with it anywhere but ANDed into
    the `WHERE` of each read of `t`, is refused, so the quarantine exclusion is always in what runs."""
    if ROWS_TOKEN not in sql:
        raise SqlError("The query must filter its rows with WHERE {{rows}}.")
    check_rows_placement(sql)
    return validate_select(sql.replace(ROWS_TOKEN, rows))
