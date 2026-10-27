"""DataCards cached per version (PRD PROF-3) in `datacards`, with `issues` and `value_index` rows.

The profile job builds the card right after import; any later request reads the stored one. Builds
of one dataset are serialized, so a request that arrives mid-build waits for it and returns the
same card (with the same issue IDs) instead of building a second one.
"""

import json
import sqlite3
import threading
from collections import defaultdict

from sherlock.cleaning import registry
from sherlock.config import Settings
from sherlock.db.util import now_iso
from sherlock.errors import not_found
from sherlock.profile.datacard import build_datacard
from sherlock.storage import VersionConnections, dataset_dir

VALUE_INDEX_ROLES = ("dimension", "target_like")
MAX_INDEXED_VALUES = 10_000
_build_locks: defaultdict[str, threading.Lock] = defaultdict(threading.Lock)
_locks_guard = threading.Lock()


def _build_lock(dataset_id: str) -> threading.Lock:
    with _locks_guard:
        return _build_locks[dataset_id]


def _stored(db: sqlite3.Connection, dataset_id: str, version: int) -> dict | None:
    row = db.execute(
        "SELECT card_json FROM datacards WHERE dataset_id = ? AND version = ?", (dataset_id, version)
    ).fetchone()
    return json.loads(row[0]) if row is not None else None


def get_or_build(
    settings: Settings,
    db: sqlite3.Connection,
    cache: VersionConnections,
    dataset: sqlite3.Row,
    version: int | None = None,
) -> dict:
    version = version or dataset["current_version"]
    row = db.execute(
        "SELECT parquet_path FROM versions WHERE dataset_id = ? AND version = ?", (dataset["id"], version)
    ).fetchone()
    if row is None:
        raise not_found(f"Version {version} not found")
    stored = _stored(db, dataset["id"], version)
    if stored is not None:
        return stored
    with _build_lock(dataset["id"]):
        stored = _stored(db, dataset["id"], version)
        if stored is not None:
            return stored  # built while this request waited
        # An undo version points at an earlier version's file, so the path comes from the row.
        folder = dataset_dir(settings, dataset["user_id"], dataset["id"])
        from sherlock.cleaning.rules import store as rule_store

        with cache.connection(dataset["id"], version, folder / row["parquet_path"]) as conn:
            card, frame = build_datacard(conn, version, rule_store.active(db, dataset["id"]))
        _store(db, dataset["id"], version, card, frame, is_current=version == dataset["current_version"])
    return card


def _store(db, dataset_id: str, version: int, card: dict, frame, is_current: bool) -> None:
    now = now_iso()
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute(
            "INSERT OR REPLACE INTO datacards (dataset_id, version, card_json, created_at) VALUES (?, ?, ?, ?)",
            (dataset_id, version, json.dumps(card), now),
        )
        db.execute("DELETE FROM issues WHERE dataset_id = ? AND version = ?", (dataset_id, version))
        db.executemany(
            "INSERT INTO issues (id, dataset_id, version, detector, detector_version, column, count, severity, details_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (i["id"], dataset_id, version, i["detector"], registry.get(i["detector"]).version, i["column"], i["count"],
                 i["severity"], json.dumps({"examples": i["examples"], "proposal": i["proposal"], **i["details"]}, default=str))
                for i in card["issues"]
            ],
        )
        if is_current:
            # The value index describes the current version only (its primary key has no version).
            db.execute("DELETE FROM value_index WHERE dataset_id = ?", (dataset_id,))
            rows = []
            for name, col in frame.columns.items():
                if col.role not in VALUE_INDEX_ROLES:
                    continue
                counts = col.raw.dropna().astype(str).value_counts().head(MAX_INDEXED_VALUES)
                rows += [(dataset_id, name, value, int(n), version) for value, n in counts.items()]
            db.executemany(
                "INSERT INTO value_index (dataset_id, column, value, count, embedding, version) "
                "VALUES (?, ?, ?, ?, NULL, ?)",
                rows,
            )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
