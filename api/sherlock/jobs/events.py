"""Events (TRD §5): every event is a `job_events` row, then a message on the in-process bus.

The row's autoincrement id is the SSE `id`, so a reconnecting client replays from the table what
it missed (`Last-Event-ID`) and the live bus carries the rest. Events that don't come from a job
(a step committed through the API, say) are written too, with `job_id` NULL, so every event can
be replayed. Every event's data carries `dataset_id`, which the user-level stream needs. The row is
written and published under one lock, so the streams get events in id order.
"""

import asyncio
import json
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import dataclass

from sherlock.db.util import now_iso

# `GET /events` carries only these (TRD §5).
USER_STREAM_TYPES = ("dataset.status", "job.progress")
REPLAY_LIMIT = 5000  # the newest this many are replayed
# Insert-then-publish under one lock: without it two threads could insert 10 and 11 and publish 11 first.
_ORDER = threading.Lock()


@dataclass(frozen=True)
class Event:
    id: int
    dataset_id: str
    user_id: str
    type: str
    data: dict

    def sse(self) -> str:
        return f"id: {self.id}\nevent: {self.type}\ndata: {json.dumps(self.data, separators=(',', ':'), default=str)}\n\n"


@dataclass(eq=False)
class Subscription:
    loop: asyncio.AbstractEventLoop
    match: Callable[[Event], bool]
    queue: asyncio.Queue


class EventBus:
    """Fan-out to the open SSE streams. `publish` is thread-safe: jobs publish from worker threads."""

    def __init__(self) -> None:
        self._subs: set[Subscription] = set()
        self._lock = threading.Lock()

    def subscribe(self, match: Callable[[Event], bool]) -> Subscription:
        """Call from the event loop that will read the queue."""
        sub = Subscription(asyncio.get_running_loop(), match, asyncio.Queue())
        with self._lock:
            self._subs.add(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        with self._lock:
            self._subs.discard(sub)

    def publish(self, event: Event) -> None:
        with self._lock:
            subs = [s for s in self._subs if s.match(event)]
        for sub in subs:
            try:
                sub.loop.call_soon_threadsafe(sub.queue.put_nowait, event)
            except RuntimeError:  # its loop has closed
                self.unsubscribe(sub)

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subs)


def emit(
    db: sqlite3.Connection,
    bus: EventBus | None,
    dataset_id: str,
    user_id: str,
    type: str,
    data: dict,
    job_id: str | None = None,
) -> Event:
    """Write the event, then publish it. Call outside a transaction, after the change it reports."""
    data = {"dataset_id": dataset_id, **data}
    with _ORDER:
        cur = db.execute(
            "INSERT INTO job_events (dataset_id, job_id, type, data_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (dataset_id, job_id, type, json.dumps(data, default=str), now_iso()),
        )
        event = Event(cur.lastrowid, dataset_id, user_id, type, data)
        if bus is not None:
            bus.publish(event)
    return event


def newest_id(db: sqlite3.Connection) -> int:
    """The highest event id so far (0 with none): a stream's opening `id:` line."""
    return db.execute("SELECT coalesce(max(id), 0) FROM job_events").fetchone()[0]


def set_dataset_status(
    db: sqlite3.Connection, bus: EventBus | None, dataset_id: str, status: str, error: str | None = None
) -> None:
    """Change a dataset's status and emit `dataset.status`."""
    db.execute("UPDATE datasets SET status = ?, error = ? WHERE id = ?", (status, error, dataset_id))
    row = db.execute("SELECT user_id, current_version FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
    data = {"status": status, "current_version": row["current_version"]}
    if error:
        data["error"] = error
    emit(db, bus, dataset_id, row["user_id"], "dataset.status", data)


def _events(rows) -> list[Event]:
    return [Event(r["id"], r["dataset_id"], r["user_id"], r["type"], json.loads(r["data_json"])) for r in rows]


# The newest REPLAY_LIMIT rows in (after, upto], sent oldest first: a client far behind gets the latest
# events, not old ones (it reads its queries again on reopen anyway).
def replay_dataset(db: sqlite3.Connection, dataset_id: str, after: int, upto: int) -> list[Event]:
    rows = db.execute(
        "SELECT * FROM (SELECT e.*, d.user_id FROM job_events e JOIN datasets d ON d.id = e.dataset_id "
        "WHERE e.dataset_id = ? AND e.id > ? AND e.id <= ? ORDER BY e.id DESC LIMIT ?) ORDER BY id",
        (dataset_id, after, upto, REPLAY_LIMIT),
    ).fetchall()
    return _events(rows)


def replay_user(db: sqlite3.Connection, user_id: str, after: int, upto: int) -> list[Event]:
    placeholders = ", ".join("?" for _ in USER_STREAM_TYPES)
    rows = db.execute(
        "SELECT * FROM (SELECT e.*, d.user_id FROM job_events e JOIN datasets d ON d.id = e.dataset_id "
        f"WHERE d.user_id = ? AND d.deleted_at IS NULL AND e.type IN ({placeholders}) AND e.id > ? AND e.id <= ? "
        "ORDER BY e.id DESC LIMIT ?) ORDER BY id",
        (user_id, *USER_STREAM_TYPES, after, upto, REPLAY_LIMIT),
    ).fetchall()
    return _events(rows)
