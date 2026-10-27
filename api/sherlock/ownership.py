"""Ownership checks (TRD §3.1): every dataset-scoped route resolves to a dataset the user owns.

Bare IDs (`/widgets/{wid}`, `/cards/{cid}`, …) are first resolved to their dataset. Anything
not owned, missing or belonging to a deleted dataset is a plain 404, never 403, so IDs from
other users are indistinguishable from IDs that don't exist.
"""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, Request

from sherlock.db.connection import get_db
from sherlock.db.users import User
from sherlock.errors import not_found
from sherlock.identity import current_user

# kind → (table, path parameter name in TRD §4)
BARE_ID_KINDS: dict[str, tuple[str, str]] = {
    "widget": ("widgets", "wid"),
    "card": ("cards", "cid"),
    "run": ("runs", "rid"),
    "export": ("exports", "export_id"),
    "job": ("jobs", "jid"),
    "proposal": ("proposals", "id"),
    "message": ("messages", "mid"),
    "fact_sheet": ("fact_sheets", "fsid"),
    "clean_plan": ("clean_plans", "pid"),
    "rule": ("detector_rules", "rid"),
}


@dataclass(frozen=True)
class Owned:
    """A resolved object: its own ID (equal to dataset_id for datasets) and its dataset."""

    id: str
    dataset_id: str | None


def check_dataset(
    conn: sqlite3.Connection, user_id: str, dataset_id: str, include_deleted: bool = False
) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM datasets WHERE id = ? AND user_id = ?", (dataset_id, user_id)
    ).fetchone()
    if row is None or (row["deleted_at"] and not include_deleted):
        raise not_found("Dataset not found")
    return row


def resolve(conn: sqlite3.Connection, user_id: str, kind: str, obj_id: str) -> Owned:
    table, _ = BARE_ID_KINDS[kind]
    if kind == "rule":
        # A rule carries its user; a check for every dataset has no dataset.
        row = conn.execute("SELECT dataset_id FROM detector_rules WHERE id = ? AND user_id = ?", (obj_id, user_id)).fetchone()
        if row is None:
            raise not_found("Rule not found")
        if row["dataset_id"]:
            check_dataset(conn, user_id, row["dataset_id"])
        return Owned(obj_id, row["dataset_id"])
    if kind == "job":
        # Jobs carry user_id directly; a purge job has no dataset.
        row = conn.execute(
            "SELECT dataset_id FROM jobs WHERE id = ? AND user_id = ?", (obj_id, user_id)
        ).fetchone()
        if row is None:
            raise not_found("Job not found")
        if row["dataset_id"]:
            check_dataset(conn, user_id, row["dataset_id"])
        return Owned(obj_id, row["dataset_id"])
    row = conn.execute(
        f"SELECT o.dataset_id FROM {table} o JOIN datasets d ON d.id = o.dataset_id "  # noqa: S608
        "WHERE o.id = ? AND d.user_id = ? AND d.deleted_at IS NULL",
        (obj_id, user_id),
    ).fetchone()
    if row is None:
        raise not_found(f"{kind.replace('_', ' ').capitalize()} not found")
    return Owned(obj_id, row["dataset_id"])


def owned_dataset(
    dataset_id: str,
    user: User = Depends(current_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> sqlite3.Row:
    """Dependency for `/datasets/{dataset_id}/…` routes."""
    return check_dataset(conn, user.id, dataset_id)


def owned(kind: str) -> Callable[..., Owned]:
    """Dependency factory for bare-ID routes, e.g. `Depends(owned("widget"))` on `/widgets/{wid}`."""
    _, param = BARE_ID_KINDS[kind]

    def dependency(
        request: Request,
        user: User = Depends(current_user),
        conn: sqlite3.Connection = Depends(get_db),
    ) -> Owned:
        return resolve(conn, user.id, kind, request.path_params[param])

    return dependency
