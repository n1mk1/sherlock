"""Apply numbered SQL migrations at startup, tracked in schema_migrations (Schema §1, §2.20)."""

import re
import sqlite3
from pathlib import Path

from sherlock.db.util import now_iso

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_NAME = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")


def available() -> list[tuple[int, Path]]:
    found = []
    for path in MIGRATIONS_DIR.iterdir():
        match = _NAME.match(path.name)
        if match:
            found.append((int(match.group(1)), path))
    return sorted(found)


def applied(conn: sqlite3.Connection) -> set[int]:
    return {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}


def migrate(conn: sqlite3.Connection) -> list[int]:
    """Apply every migration not yet recorded, each in its own transaction. Returns the new ones."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    done = applied(conn)
    new = []
    for version, path in available():
        if version in done:
            continue
        script = path.read_text(encoding="utf-8")
        try:
            conn.executescript(
                f"BEGIN;\n{script}\n"
                f"INSERT INTO schema_migrations (version, applied_at) VALUES ({version}, '{now_iso()}');\n"
                "COMMIT;"
            )
        except sqlite3.Error:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        new.append(version)
    return new


def current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    return row[0] or 0
