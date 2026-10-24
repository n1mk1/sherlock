"""users repository (Schema §2.1). Cookie tokens are stored only as sha256 hashes."""

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from sherlock.db.util import new_id, now_iso

LAST_SEEN_RESOLUTION = timedelta(minutes=1)


@dataclass(frozen=True)
class User:
    id: str
    created_at: str
    settings: dict


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _from_row(row: sqlite3.Row) -> User:
    return User(id=row["id"], created_at=row["created_at"], settings=json.loads(row["settings_json"]))


def get_by_token(conn: sqlite3.Connection, token: str) -> User | None:
    row = conn.execute(
        "SELECT id, created_at, settings_json, last_seen_at FROM users WHERE cookie_token = ?",
        (hash_token(token),),
    ).fetchone()
    if row is None:
        return None
    _touch(conn, row["id"], row["last_seen_at"])
    return _from_row(row)


def get(conn: sqlite3.Connection, user_id: str) -> User | None:
    row = conn.execute(
        "SELECT id, created_at, settings_json FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    return _from_row(row) if row else None


def create(conn: sqlite3.Connection, token: str) -> User:
    now = now_iso()
    user_id = new_id("usr")
    conn.execute(
        "INSERT INTO users (id, cookie_token, created_at, last_seen_at) VALUES (?, ?, ?, ?)",
        (user_id, hash_token(token), now, now),
    )
    return User(id=user_id, created_at=now, settings={})


def save_settings(conn: sqlite3.Connection, user_id: str, settings: dict) -> None:
    conn.execute(
        "UPDATE users SET settings_json = ? WHERE id = ?", (json.dumps(settings), user_id)
    )


def _touch(conn: sqlite3.Connection, user_id: str, last_seen_at: str) -> None:
    """Refresh last_seen_at at most once a minute, so reads don't write on every request."""
    last = datetime.fromisoformat(last_seen_at.replace("Z", "+00:00"))
    now = datetime.fromisoformat(now_iso().replace("Z", "+00:00"))
    if now - last >= LAST_SEEN_RESOLUTION:
        conn.execute("UPDATE users SET last_seen_at = ? WHERE id = ?", (now_iso(), user_id))
