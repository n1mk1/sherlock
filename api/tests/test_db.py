import re
import sqlite3

import pytest

from sherlock.config import get_settings
from sherlock.db.connection import connect, sqlite_path
from sherlock.db.migrate import applied, available, current_version, migrate
from sherlock.db.util import new_id, now_iso, ulid


@pytest.fixture
def conn():
    c = connect(get_settings())
    migrate(c)
    yield c
    c.close()


def test_migrate_is_idempotent_and_tracked(conn):
    assert migrate(conn) == []
    # Every numbered file is applied once; the newest is the version (each slice adds its own file).
    assert applied(conn) == {v for v, _ in available()} and current_version(conn) == available()[-1][0] >= 4


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


def test_migration_013_drops_the_surfaces_from_a_database_that_had_them(monkeypatch):
    """Cuts 10 to 12 (plan §5): on a database made before them, 013 applies with rows in the old tables;
    a dataset left building is ready, a remembered Dashboard tab opens the CSV, the surface jobs stop,
    and only the analyses' fact sheets stay."""
    from sherlock.db import migrate as migrate_mod

    every = available()
    c = connect(get_settings())
    try:
        monkeypatch.setattr(migrate_mod, "available", lambda: [(v, p) for v, p in every if v < 13])
        migrate(c)
        assert current_version(c) == 12
        now = now_iso()
        c.execute("INSERT INTO users (id, cookie_token, created_at, last_seen_at) VALUES ('usr_a', 'h', ?, ?)", (now, now))
        for ds, status, tab in (("ds_b", "building", "dashboard"), ("ds_r", "ready", "flow"), ("ds_o", "offer", "csv")):
            c.execute("INSERT INTO datasets (id, user_id, name, original_filename, status, import_options_json, expires_at, "
                      "created_at, last_tab) VALUES (?, 'usr_a', 'x', 'x.csv', ?, '{}', ?, ?, ?)", (ds, status, now, now, tab))
        for jid, kind, status in (("job_c", "cascade", "running"), ("job_s", "stories", "queued"),
                                  ("job_d", "build_dashboard", "done"), ("job_p", "profile", "queued")):
            c.execute("INSERT INTO jobs (id, dataset_id, user_id, kind, status, created_at) VALUES (?, 'ds_b', 'usr_a', ?, ?, ?)",
                      (jid, kind, status, now))
        c.execute("INSERT INTO widgets (id, dataset_id, title, spec_json, spec_hash, status, version_built, created_by, "
                  "order_no, created_at, updated_at) VALUES ('wdg_1', 'ds_r', 't', '{}', 'h', 'ready', 1, 'builder', 0, ?, ?)",
                  (now, now))
        c.execute("INSERT INTO runs (id, dataset_id, widget_id, version, recipe, method, scope_json, params_json, cache_key, "
                  "status, created_by, created_at) VALUES ('run_1', 'ds_r', 'wdg_1', 1, 'driver_analysis', 'auto', '{}', "
                  "'{}', 'k', 'done', 'builder', ?)", (now,))
        for fs, wid, rid in (("fs_w", "wdg_1", None), ("fs_r", None, "run_1"), ("fs_o", None, None)):
            c.execute("INSERT INTO fact_sheets (id, dataset_id, widget_id, run_id, version, facts_json, depends_columns_json, "
                      "material_hash, created_at) VALUES (?, 'ds_r', ?, ?, 1, '[]', '[]', 'm', ?)", (fs, wid, rid, now))

        monkeypatch.setattr(migrate_mod, "available", lambda: every)
        assert migrate(c) == [v for v, _ in every if v >= 13]
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not {"widgets", "layouts", "widget_cache", "relations", "cards", "canvases"} & tables
        assert "widget_id" not in {r[1] for r in c.execute("PRAGMA table_info(runs)")}
        assert "widget_id" not in {r[1] for r in c.execute("PRAGMA table_info(fact_sheets)")}
        assert {r[0]: (r[1], r[2]) for r in c.execute("SELECT id, status, last_tab FROM datasets")} == {
            "ds_b": ("ready", "csv"), "ds_r": ("ready", "csv"), "ds_o": ("offer", "csv")}
        assert {r[0]: r[1] for r in c.execute("SELECT id, status FROM jobs")} == {
            "job_c": "cancelled", "job_s": "cancelled", "job_d": "done", "job_p": "queued"}
        assert [r[0] for r in c.execute("SELECT id FROM fact_sheets")] == ["fs_r"]
        assert c.execute("SELECT status FROM runs WHERE id = 'run_1'").fetchone()[0] == "done"
    finally:
        c.close()
