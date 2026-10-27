"""What query work needs (TRD §6.3, §9): settings, one SQLite connection, the DuckDB cache and the
event bus, plus the helpers chat, ML and the routers share to reach a version's rows."""

import json
import sqlite3
from dataclasses import dataclass

from sherlock.config import Settings
from sherlock.errors import not_found
from sherlock.jobs.events import EventBus
from sherlock.query import compile as qc
from sherlock.rows.query import SYSTEM, describe
from sherlock.storage import VersionConnections, dataset_dir


@dataclass
class Env:
    """Settings, one SQLite connection, the DuckDB cache and the event bus."""
    settings: Settings
    db: sqlite3.Connection
    cache: VersionConnections
    bus: EventBus | None


def version_row(db: sqlite3.Connection, dataset_id: str, version: int) -> sqlite3.Row:
    row = db.execute("SELECT * FROM versions WHERE dataset_id = ? AND version = ?", (dataset_id, version)).fetchone()
    if row is None:
        raise not_found(f"Version {version} not found")
    return row


def connection(env: Env, dataset: sqlite3.Row, version: int):
    vrow = version_row(env.db, dataset["id"], version)
    folder = dataset_dir(env.settings, dataset["user_id"], dataset["id"])
    return env.cache.connection(dataset["id"], version, folder / vrow["parquet_path"])


def user_types(env: Env, dataset: sqlite3.Row, version: int) -> dict[str, str]:
    with connection(env, dataset, version) as conn:
        return {c: t for c, t in describe(conn).items() if c not in SYSTEM}


def selection_sql(db: sqlite3.Connection, dataset_id: str, selection_id: str) -> str:
    sel = db.execute("SELECT * FROM selections WHERE id = ? AND dataset_id = ?", (selection_id, dataset_id)).fetchone()
    if sel is None:
        raise not_found("Selection not found")
    if sel["row_ids_json"]:
        ids = json.loads(sel["row_ids_json"])
        return f"_row_id IN ({', '.join(str(int(i)) for i in ids)})" if ids else "FALSE"
    return sel["predicate"] or "1=1"


def selection_rows(env: Env, dataset: sqlite3.Row, selection_id: str) -> int | None:
    """How many usable rows a selection holds on the current version, counted when it's read (Schema §2.16):
    its stored `row_count` is from the version it was made on, and an edit, an undo or a clean
    since then can change it. None when the selection isn't this CSV's."""
    if env.db.execute("SELECT 1 FROM selections WHERE id = ? AND dataset_id = ?", (selection_id, dataset["id"])).fetchone() is None:
        return None
    where = qc.rows_clause(None, selection_sql(env.db, dataset["id"], selection_id), None)
    with connection(env, dataset, dataset["current_version"]) as conn:
        return conn.execute(f"SELECT count(*) FROM t WHERE {where}").fetchone()[0]  # noqa: S608 - validated SQL


def bump_state(db: sqlite3.Connection, dataset_id: str) -> None:
    """A new export cache key (Schema §2.2 `state_rev`)."""
    db.execute("UPDATE datasets SET state_rev = state_rev + 1 WHERE id = ?", (dataset_id,))
