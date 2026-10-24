"""DataCards cached per version (PRD PROF-3) in `datacards`, with `issues` and `value_index` rows.

The card is built on first request for a version and stored; later requests read the stored one.
The profile job (Implementation Plan D2.5) will call `get_or_build` right after import.
"""

import json
import sqlite3

from sherlock.config import Settings
from sherlock.db.util import now_iso
from sherlock.errors import not_found
from sherlock.profile.datacard import build_datacard
from sherlock.storage import VersionConnections, dataset_dir

VALUE_INDEX_ROLES = ("dimension", "target_like")
MAX_INDEXED_VALUES = 10_000


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
    stored = db.execute(
        "SELECT card_json FROM datacards WHERE dataset_id = ? AND version = ?", (dataset["id"], version)
    ).fetchone()
    if stored is not None:
        return json.loads(stored[0])

    # An undo version points at an earlier version's file, so the path comes from the row.
    folder = dataset_dir(settings, dataset["user_id"], dataset["id"])
    with cache.connection(dataset["id"], version, folder / row["parquet_path"]) as conn:
        card, frame = build_datacard(conn, version)
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
            "INSERT INTO issues (id, dataset_id, version, detector, column, count, severity, details_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (i["id"], dataset_id, version, i["detector"], i["column"], i["count"], i["severity"],
                 json.dumps({"examples": i["examples"], "proposal": i["proposal"], **i["details"]}, default=str))
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
