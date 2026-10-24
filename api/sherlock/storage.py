"""Per-dataset file layout (Schema §4) and the cached in-memory DuckDB connections (TRD §3.2).

Versions are immutable Parquet files. Queries never touch them directly: each (dataset,
version) gets one in-memory DuckDB connection that loads the Parquet as table `t` and then
turns off external access, so validated SQL can only read `t`.
"""

import shutil
import threading
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import duckdb

from sherlock.config import Settings

MAX_CACHED_CONNECTIONS = 4


def sql_path(path: Path) -> str:
    """A path as a single-quoted DuckDB string literal."""
    return "'" + path.resolve().as_posix().replace("'", "''") + "'"


def dataset_dir(settings: Settings, user_id: str, dataset_id: str) -> Path:
    return settings.data_dir / "users" / user_id / "datasets" / dataset_id


def raw_path(folder: Path) -> Path:
    return folder / "raw.csv"


def version_path(folder: Path, version: int) -> Path:
    return folder / "versions" / f"v{version}.parquet"


def folder_bytes(folder: Path) -> int:
    return sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())


def remove_folder(folder: Path) -> None:
    shutil.rmtree(folder, ignore_errors=True)


def new_duckdb(settings: Settings, temp_dir: Path | None = None) -> duckdb.DuckDBPyConnection:
    """An in-memory DuckDB connection inside the memory budget (`DUCKDB_MEMORY_MB`)."""
    conn = duckdb.connect(":memory:")
    conn.execute(f"SET memory_limit='{settings.duckdb_memory_mb}MB'")
    conn.execute("SET threads=2")
    if temp_dir is not None:
        conn.execute(f"SET temp_directory={sql_path(temp_dir)}")
    return conn


class _Entry:
    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self.conn = conn
        self.lock = threading.Lock()


class VersionConnections:
    """LRU of in-memory connections per (dataset, version), at most four.

    Opening a version evicts the dataset's older versions. A connection is used by one
    request at a time (DuckDB connections aren't safe to share across threads mid-query).
    """

    def __init__(self, settings: Settings, max_size: int = MAX_CACHED_CONNECTIONS) -> None:
        self.settings = settings
        self.max_size = max_size
        self._entries: OrderedDict[tuple[str, int], _Entry] = OrderedDict()
        self._lock = threading.Lock()

    def _open(self, parquet: Path) -> _Entry:
        conn = new_duckdb(self.settings)
        conn.execute(f"CREATE TABLE t AS SELECT * FROM read_parquet({sql_path(parquet)})")
        conn.execute("SET enable_external_access=false")
        return _Entry(conn)

    def _entry(self, dataset_id: str, version: int, parquet: Path) -> _Entry:
        key = (dataset_id, version)
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                self._entries.move_to_end(key)
                return entry
            for old in [k for k in self._entries if k[0] == dataset_id and k[1] < version]:
                self._entries.pop(old).conn.close()
            entry = self._open(parquet)
            self._entries[key] = entry
            while len(self._entries) > self.max_size:
                _, evicted = self._entries.popitem(last=False)
                evicted.conn.close()
            return entry

    @contextmanager
    def connection(self, dataset_id: str, version: int, parquet: Path) -> Iterator[duckdb.DuckDBPyConnection]:
        entry = self._entry(dataset_id, version, parquet)
        with entry.lock:
            yield entry.conn

    def drop(self, dataset_id: str) -> None:
        with self._lock:
            for key in [k for k in self._entries if k[0] == dataset_id]:
                self._entries.pop(key).conn.close()

    def close(self) -> None:
        with self._lock:
            for entry in self._entries.values():
                entry.conn.close()
            self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)
