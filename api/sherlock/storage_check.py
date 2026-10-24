"""Startup check of the /data volume (Implementation Plan D1.3 exit check, TRD §3.2).

Records each boot in `<DATA_DIR>/.boots`, so `boots > 1` after a restart proves the
volume persists, and checks that SQLite write locks work on it: a second connection must
be refused while the first holds `BEGIN IMMEDIATE`.
"""

import sqlite3
from pathlib import Path

from sherlock.config import Settings
from sherlock.db.util import now_iso

BOOTS_FILE = ".boots"
LOCK_DB = ".lockcheck.db"


def _record_boot(data_dir: Path) -> tuple[int, str]:
    path = data_dir / BOOTS_FILE
    with path.open("a", encoding="utf-8") as fh:
        fh.write(now_iso() + "\n")
    lines = path.read_text(encoding="utf-8").splitlines()
    return len(lines), lines[0]


def _sqlite_lock_works(data_dir: Path) -> bool:
    path = data_dir / LOCK_DB
    holder = sqlite3.connect(path, timeout=0.2, isolation_level=None)
    other = sqlite3.connect(path, timeout=0.2, isolation_level=None)
    try:
        holder.execute("PRAGMA journal_mode=WAL")
        holder.execute("CREATE TABLE IF NOT EXISTS t (x INTEGER)")
        holder.execute("BEGIN IMMEDIATE")
        holder.execute("INSERT INTO t VALUES (1)")
        try:
            other.execute("BEGIN IMMEDIATE")
            other.execute("ROLLBACK")
            refused = False  # the lock was not exclusive: unsafe for SQLite
        except sqlite3.OperationalError:
            refused = True
        holder.execute("COMMIT")
        other.execute("BEGIN IMMEDIATE")  # free again after the commit
        other.execute("DELETE FROM t")
        other.execute("COMMIT")
        return refused
    finally:
        holder.close()
        other.close()


def check_storage(settings: Settings) -> dict:
    data_dir = settings.data_dir
    result = {"data_dir": str(data_dir), "writable": False, "boots": 0, "first_boot_at": None,
              "sqlite_lock": False}
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        result["boots"], result["first_boot_at"] = _record_boot(data_dir)
        result["writable"] = True
        result["sqlite_lock"] = _sqlite_lock_works(data_dir)
    except (OSError, sqlite3.Error) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result
