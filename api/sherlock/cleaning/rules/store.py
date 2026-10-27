"""Rules as stored (Schema §2.25 `detector_rules`, PRD CLEAN-13): a dataset's checks, with their source
(`user`, `suggested`, `pack`) and status (`active`, `suggested`, `off`). Only `active` rules run."""

import json
import sqlite3

from sherlock.db.util import new_id, now_iso


def _out(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "source": row["source"], "status": row["status"], **json.loads(row["spec_json"])}


def get(db: sqlite3.Connection, rule_id: str) -> dict | None:
    row = db.execute("SELECT * FROM detector_rules WHERE id = ?", (rule_id,)).fetchone()
    return _out(row) | {"dataset_id": row["dataset_id"], "user_id": row["user_id"]} if row else None


def all_for(db: sqlite3.Connection, dataset_id: str) -> list[dict]:
    rows = db.execute("SELECT * FROM detector_rules WHERE dataset_id = ? ORDER BY rowid", (dataset_id,)).fetchall()  # saved order
    return [_out(r) for r in rows]


def active(db: sqlite3.Connection, dataset_id: str) -> list[dict]:
    return [r for r in all_for(db, dataset_id) if r["status"] == "active"]


def create(db: sqlite3.Connection, user_id: str, dataset_id: str, spec: dict, source: str = "user",
           status: str = "active") -> dict:
    rid, now = new_id("rul"), now_iso()
    db.execute("INSERT INTO detector_rules (id, user_id, dataset_id, source, status, spec_json, created_at, updated_at) "
               "VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (rid, user_id, dataset_id, source, status, json.dumps(spec), now, now))
    return get(db, rid)


def update(db: sqlite3.Connection, rule_id: str, spec: dict | None = None, status: str | None = None) -> dict:
    if spec is not None:
        db.execute("UPDATE detector_rules SET spec_json = ?, updated_at = ? WHERE id = ?", (json.dumps(spec), now_iso(), rule_id))
    if status is not None:
        db.execute("UPDATE detector_rules SET status = ?, updated_at = ? WHERE id = ?", (status, now_iso(), rule_id))
    return get(db, rule_id)
