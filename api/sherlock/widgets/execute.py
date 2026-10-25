"""Running a compiled widget query (TRD §6.3, §9): the cached in-memory DuckDB connection with
external access off, a 10 s watchdog, at most 2,000 result rows, and the widget data cache (an
in-memory LRU of 500 entries over the `widget_cache` table, keyed by spec hash, version and filter
hash)."""

import hashlib
import json
import sqlite3
import threading
from collections import OrderedDict

import duckdb

from sherlock.db.util import now_iso
from sherlock.rows.query import json_value
from sherlock.widgets.compile import MAX_RESULT_ROWS, SqlError

TIMEOUT_S = 10.0
LRU_SIZE = 500


def run_query(conn: duckdb.DuckDBPyConnection, sql: str, timeout_s: float = TIMEOUT_S) -> dict:
    """`{columns: [{name, type}], rows, row_count, truncated}` for one validated query."""
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
    return {
        "columns": columns,
        "rows": [[json_value(v) for v in r] for r in rows],
        "row_count": len(rows),
        "truncated": truncated,
    }


def cache_key(spec_hash: str, version: int, filter_sql: str | None) -> str:
    filter_hash = hashlib.sha1((filter_sql or "").encode()).hexdigest()
    return hashlib.sha1(f"{spec_hash}:{version}:{filter_hash}".encode()).hexdigest()


class WidgetCache:
    """The in-memory front of `widget_cache`. Entries are immutable per key, so there is nothing to
    invalidate: a new version is a new key."""

    def __init__(self, size: int = LRU_SIZE) -> None:
        self.size = size
        self._data: OrderedDict[tuple[str, str], dict] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, db: sqlite3.Connection, dataset_id: str, key: str) -> dict | None:
        with self._lock:
            hit = self._data.get((dataset_id, key))
            if hit is not None:
                self._data.move_to_end((dataset_id, key))
                return hit
        row = db.execute(
            "SELECT data_json FROM widget_cache WHERE dataset_id = ? AND cache_key = ?", (dataset_id, key)
        ).fetchone()
        if row is None:
            return None
        data = json.loads(row[0])
        self._remember(dataset_id, key, data)
        return data

    def put(self, db: sqlite3.Connection, dataset_id: str, key: str, data: dict) -> None:
        db.execute(
            "INSERT OR REPLACE INTO widget_cache (dataset_id, cache_key, data_json, created_at) VALUES (?, ?, ?, ?)",
            (dataset_id, key, json.dumps(data, default=str), now_iso()),
        )
        self._remember(dataset_id, key, data)

    def _remember(self, dataset_id: str, key: str, data: dict) -> None:
        with self._lock:
            self._data[(dataset_id, key)] = data
            self._data.move_to_end((dataset_id, key))
            while len(self._data) > self.size:
                self._data.popitem(last=False)

    def drop(self, dataset_id: str) -> None:
        with self._lock:
            for k in [k for k in self._data if k[0] == dataset_id]:
                del self._data[k]


CACHE = WidgetCache()
