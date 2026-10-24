"""datasets repository (Schema §2.2)."""

import sqlite3

from sherlock.db.util import now_iso

_INSERT_COLUMNS = (
    "id", "user_id", "name", "original_filename", "is_sample", "status", "current_version",
    "row_count", "column_count", "import_options_json", "expires_at", "folder_bytes",
    "next_row_id", "created_at",
)


def insert(conn: sqlite3.Connection, **values) -> None:
    values["is_sample"] = int(values["is_sample"])
    placeholders = ", ".join("?" for _ in _INSERT_COLUMNS)
    conn.execute(
        f"INSERT INTO datasets ({', '.join(_INSERT_COLUMNS)}) VALUES ({placeholders})",
        tuple(values[c] for c in _INSERT_COLUMNS),
    )


def get(conn: sqlite3.Connection, user_id: str, dataset_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM datasets WHERE id = ? AND user_id = ? AND deleted_at IS NULL",
        (dataset_id, user_id),
    ).fetchone()


def list_for_user(conn: sqlite3.Connection, user_id: str) -> list[sqlite3.Row]:
    """Most recently opened first, then newest (Schema index `datasets_user`)."""
    return conn.execute(
        "SELECT * FROM datasets WHERE user_id = ? AND deleted_at IS NULL "
        "ORDER BY last_opened_at IS NULL, last_opened_at DESC, created_at DESC",
        (user_id,),
    ).fetchall()


def find_sample(conn: sqlite3.Connection, user_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM datasets WHERE user_id = ? AND is_sample = 1 AND deleted_at IS NULL "
        "ORDER BY created_at LIMIT 1",
        (user_id,),
    ).fetchone()


def mark_opened(conn: sqlite3.Connection, dataset_id: str) -> None:
    conn.execute("UPDATE datasets SET last_opened_at = ? WHERE id = ?", (now_iso(), dataset_id))
