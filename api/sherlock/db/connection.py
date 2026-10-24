"""SQLite connections with the Schema §1 pragmas; one connection per request (TRD §3.2)."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

from fastapi import Request

from sherlock.config import Settings

PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA busy_timeout=5000",
    "PRAGMA synchronous=NORMAL",
)


def sqlite_path(database_url: str) -> Path:
    """`sqlite:////data/sherlock.db` → `/data/sherlock.db`; `sqlite:///./x.db` → `./x.db`."""
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError(f"DATABASE_URL must start with {prefix!r}")
    return Path(database_url[len(prefix) :])


def connect(settings: Settings) -> sqlite3.Connection:
    path = sqlite_path(settings.database_url)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Autocommit mode: writes that must be atomic open an explicit transaction.
    conn = sqlite3.connect(path, timeout=5.0, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    for pragma in PRAGMAS:
        conn.execute(pragma)
    return conn


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: a connection for this request, closed when it ends."""
    conn = connect(request.app.state.settings)
    try:
        yield conn
    finally:
        conn.close()
