import re
import sqlite3
from pathlib import Path

import pytest

from sherlock.config import get_settings
from sherlock.db.connection import connect, sqlite_path
from sherlock.db.migrate import current_version, migrate
from sherlock.db.util import new_id, now_iso, ulid

SCHEMA_DOC = Path(__file__).resolve().parents[2] / "docs" / "05-BACKEND-SCHEMA.md"


def doc_tables() -> dict[str, list[str]]:
    """Table → column names, parsed from the schema doc's CREATE TABLE blocks."""
    tables = {}
    text = SCHEMA_DOC.read_text(encoding="utf-8")
    # A multi-line block opens with a newline, so a one-line table can't run on into the next block.
    multi_line = re.findall(r"CREATE TABLE (\w+) \(\n(.*?)\n\)", text, re.S)
    one_line = re.findall(r"CREATE TABLE (\w+) \(([^\n]*)\);", text)
    for name, body in multi_line + one_line:
        columns = []
        for line in body.splitlines():
            line = line.split("--")[0].strip()
            if not line or line.split(" ")[0] in {"PRIMARY", "FOREIGN", "UNIQUE"}:
                continue  # table constraints, not columns
            for part in line.split(","):
                word = part.strip().split(" ")[0]
                if word and re.fullmatch(r"[a-z_]+", word):
                    columns.append(word)
        tables[name] = columns
    return tables


@pytest.fixture
def conn():
    c = connect(get_settings())
    migrate(c)
    yield c
    c.close()


def test_migration_matches_schema_doc(conn):
    expected = doc_tables()
    actual = {
        r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if r[0] != "sqlite_sequence"
    }
    assert actual == set(expected)
    for table, columns in expected.items():
        got = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        assert got == columns, table


def test_migrate_is_idempotent_and_tracked(conn):
    assert migrate(conn) == []
    assert current_version(conn) == 2


def test_pragmas(conn):
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000


def test_foreign_keys_cascade(conn):
    now = now_iso()
    conn.execute("INSERT INTO users (id, cookie_token, created_at, last_seen_at) VALUES ('usr_a', 'h', ?, ?)", (now, now))
    conn.execute(
        "INSERT INTO datasets (id, user_id, name, original_filename, status, import_options_json, expires_at, created_at) "
        "VALUES ('ds_a', 'usr_a', 'x', 'x.csv', 'ready', '{}', ?, ?)", (now, now),
    )
    conn.execute("DELETE FROM users WHERE id = 'usr_a'")
    assert conn.execute("SELECT COUNT(*) FROM datasets").fetchone()[0] == 0
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO datasets (id, user_id, name, original_filename, status, import_options_json, expires_at, created_at) "
            "VALUES ('ds_b', 'usr_missing', 'x', 'x.csv', 'ready', '{}', ?, ?)", (now, now),
        )


def test_ids_and_timestamps():
    a, b = ulid(), ulid()
    assert len(a) == 26 and re.fullmatch(r"[0-9A-HJKMNP-TV-Z]{26}", a)
    assert a[:10] <= b[:10]  # time prefix sorts by creation
    assert new_id("usr").startswith("usr_")
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", now_iso())


def test_sqlite_path():
    assert sqlite_path("sqlite:////data/sherlock.db").as_posix() == "/data/sherlock.db"
    assert sqlite_path("sqlite:///./data/sherlock.db").as_posix() == "data/sherlock.db"
    with pytest.raises(ValueError):
        sqlite_path("postgres://x")
