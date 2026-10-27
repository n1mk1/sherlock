"""Running a compiled query (TRD §6.3, §9): the cached in-memory DuckDB connection with external
access off, a 10 s watchdog and at most 2,000 result rows."""

import threading

import duckdb

from sherlock.rows.query import json_value
from sherlock.query.compile import MAX_RESULT_ROWS, SqlError

TIMEOUT_S = 10.0


def run_query(conn: duckdb.DuckDBPyConnection, sql: str, timeout_s: float = TIMEOUT_S) -> dict:
    """`{columns: [{name, type}], rows, row_count, truncated, total}` for one validated query. `row_count`
    counts the rows returned (at most `MAX_RESULT_ROWS`); `total` is the query's real row count, counted
    again when the rows were capped."""
    timer = threading.Timer(timeout_s, conn.interrupt)
    timer.daemon = True
    timer.start()
    try:
        rel = conn.sql(sql)
        columns = [{"name": n, "type": str(t)} for n, t in zip(rel.columns, rel.types)]
        rows = rel.fetchmany(MAX_RESULT_ROWS + 1)
    except duckdb.InterruptException:
        raise SqlError(f"The query took longer than {timeout_s:.0f} s and was stopped.") from None
    except duckdb.Error as exc:
        first = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        raise SqlError(f"The query failed: {first[:300]}") from None
    finally:
        timer.cancel()
    truncated = len(rows) > MAX_RESULT_ROWS
    rows = rows[:MAX_RESULT_ROWS]
    total = len(rows)
    if truncated:
        try:
            total = conn.sql(f"SELECT count(*) FROM ({sql}) AS capped").fetchone()[0]
        except duckdb.Error:
            total = len(rows)
    return {
        "columns": columns,
        "rows": [[json_value(v) for v in r] for r in rows],
        "row_count": len(rows),
        "truncated": truncated,
        "total": total,
    }
