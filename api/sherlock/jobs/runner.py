"""The job runner (TRD §3.3): `JOB_WORKERS` asyncio tasks claiming queued jobs from SQLite.

A claim is one `UPDATE … RETURNING` statement, so no job runs twice. A job kind is an async
function that does its blocking work through `asyncio.to_thread`; it reports through its
`JobContext` (progress, log lines, dataset status), each of which is a `job_events` row plus a
bus message. A running job refreshes `heartbeat_at` every 10 s. One process holds the runner, so
at startup every job still marked running was orphaned by the previous process and is re-queued;
a sweep also re-queues any running job of another process whose heartbeat is older than 60 s.
A job kind can checkpoint (`ctx.checkpoint(state)` writes `state_json`); a re-queued job gets that
state back as `ctx.state` and resumes from it (D8.6). Kinds without checkpoints start over, which is
safe because job kinds are idempotent. The sweeper also queues the `purge` job every
`PURGE_INTERVAL_S` (Schema §6).

The kinds that write a dataset's widgets and cards (`SERIAL_KINDS`) run one at a time per dataset:
the claim skips a queued one while another of them runs for its dataset, so an older update can't
land after a newer one (plan 1.1).
"""

import asyncio
import json
import logging
import os
import socket
import sqlite3
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sherlock.config import Settings
from sherlock.db.connection import connect
from sherlock.db.util import new_id, now_iso, ulid
from sherlock.jobs.events import EventBus, emit, set_dataset_status
from sherlock.storage import VersionConnections

log = logging.getLogger("sherlock.jobs")

KINDS = ("profile", "clean", "build_dashboard", "stories", "ml_run", "cascade", "undo", "export_notebook", "purge")
# At most one of these runs per dataset at a time: each writes the dataset's widgets and story cards.
SERIAL_KINDS = ("cascade", "stories", "build_dashboard")
_SERIAL = ", ".join(f"'{k}'" for k in SERIAL_KINDS)
FINISHED = ("done", "failed", "cancelled")
HEARTBEAT_S = 10.0
STALE_S = 60.0
SWEEP_S = 30.0
POLL_S = 1.0
STOP_GRACE_S = 10.0


class JobCancelled(Exception):
    """Raised by `JobContext.check_cancel` when the user asked to cancel."""


@dataclass(frozen=True)
class JobKind:
    run: Callable[["JobContext"], Awaitable[dict | None]]
    # Called when a job of this kind fails or is cancelled, e.g. to mark its dataset failed.
    on_failure: Callable[[sqlite3.Connection, EventBus | None, sqlite3.Row, str], None] | None = None


HANDLERS: dict[str, JobKind] = {}


def register(kind: str, run, on_failure=None) -> None:
    if kind not in KINDS:
        raise ValueError(f"unknown job kind {kind!r}")
    HANDLERS[kind] = JobKind(run, on_failure)


def _ago(seconds: float) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _progress(row: sqlite3.Row) -> dict:
    if row["progress_json"]:
        return json.loads(row["progress_json"])
    return {"step": 0, "of": 0, "label": "", "pct": 0}


def to_job(row: sqlite3.Row) -> dict:
    """A job in the TRD §4.10 `Job` shape."""
    job = {
        "id": row["id"], "dataset_id": row["dataset_id"], "kind": row["kind"], "status": row["status"],
        "progress": _progress(row), "created_at": row["created_at"], "started_at": row["started_at"],
        "finished_at": row["finished_at"], "error": row["error"],
        "result": json.loads(row["result_json"]) if row["result_json"] else None,
        # Queued by the "After upload" setting rather than a click (App Flow §4).
        "automatic": bool(json.loads(row["params_json"] or "{}").get("automatic")),
    }
    return job


def get_job(db: sqlite3.Connection, job_id: str) -> sqlite3.Row:
    return db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def insert_job(
    db: sqlite3.Connection, user_id: str, dataset_id: str | None, kind: str, params: dict | None = None
) -> sqlite3.Row:
    if kind not in KINDS:
        raise ValueError(f"unknown job kind {kind!r}")
    job_id = new_id("job")
    db.execute(
        "INSERT INTO jobs (id, dataset_id, user_id, kind, status, params_json, created_at) "
        "VALUES (?, ?, ?, ?, 'queued', ?, ?)",
        (job_id, dataset_id, user_id, kind, json.dumps(params or {}), now_iso()),
    )
    return get_job(db, job_id)


def _end_event(db: sqlite3.Connection, bus: EventBus | None, row: sqlite3.Row) -> None:
    if row["dataset_id"] is None:
        return  # events are per dataset; a purge job has none
    kind = "job.done" if row["status"] == "done" else "job.failed"  # a cancelled job ends with job.failed
    emit(db, bus, row["dataset_id"], row["user_id"], kind, to_job(row), job_id=row["id"])


def cancel_job(db: sqlite3.Connection, bus: EventBus | None, job_id: str) -> None:
    """A queued job is cancelled at once; a running one at its next `check_cancel`."""
    cur = db.execute(
        "UPDATE jobs SET status = 'cancelled', cancel_requested = 1, finished_at = ?, error = ? "
        "WHERE id = ? AND status = 'queued'",
        (now_iso(), "Cancelled.", job_id),
    )
    if cur.rowcount:
        row = get_job(db, job_id)
        _failure_hook(db, bus, row, "Cancelled.")
        _end_event(db, bus, row)
        return
    db.execute("UPDATE jobs SET cancel_requested = 1 WHERE id = ? AND status = 'running'", (job_id,))


def _failure_hook(db, bus, row: sqlite3.Row, message: str) -> None:
    kind = HANDLERS.get(row["kind"])
    if kind and kind.on_failure:
        try:
            kind.on_failure(db, bus, row, message)
        except Exception:
            log.exception("on_failure of job %s failed", row["id"])


class JobContext:
    """What a running job uses to report. Its methods are synchronous and thread-safe, so a job
    can call them from the thread doing its blocking work."""

    def __init__(self, runner: "JobRunner", row: sqlite3.Row) -> None:
        self.runner = runner
        self.settings: Settings = runner.settings
        self.bus = runner.bus
        self.cache: VersionConnections = runner.cache
        self.row = row
        self.id: str = row["id"]
        self.kind: str = row["kind"]
        self.dataset_id: str | None = row["dataset_id"]
        self.user_id: str = row["user_id"]
        self.params: dict = json.loads(row["params_json"])
        # The last checkpoint, when the job was re-queued mid-run (after a restart or a stale heartbeat).
        self.state: dict = json.loads(row["state_json"]) if row["state_json"] else {}
        self.db = connect(self.settings)
        self._lock = threading.RLock()

    def checkpoint(self, state: dict) -> None:
        """Save how far the job got, so a re-queued run can carry on from here (TRD §3.3)."""
        with self._lock:
            self.state = state
            self.db.execute("UPDATE jobs SET state_json = ? WHERE id = ?", (json.dumps(state), self.id))

    def close(self) -> None:
        with self._lock:
            self.db.close()

    def emit(self, type: str, data: dict) -> None:
        with self._lock:
            emit(self.db, self.bus, self.dataset_id, self.user_id, type, data, job_id=self.id)

    def progress(self, step: int, of: int, label: str, pct: float | None = None) -> None:
        """`step` is the one now running (1-based); `pct` defaults to the share of steps done."""
        if pct is None:
            pct = round(100 * (step - 1) / of, 1) if of else 0
        progress = {"step": step, "of": of, "label": label, "pct": pct}
        with self._lock:
            self.db.execute("UPDATE jobs SET progress_json = ? WHERE id = ?", (json.dumps(progress), self.id))
            if self.dataset_id:
                self.emit("job.progress", {**progress, "job_id": self.id, "kind": self.kind})

    def log(self, text: str, level: str = "info", icon: str = "info", **fields) -> None:
        """A `job.log` line (TRD §5.1), kept for `GET /jobs/{jid}/log`."""
        if self.dataset_id:
            self.emit("job.log", {"job_id": self.id, "ts": now_iso(), "level": level, "icon": icon, "text": text, **fields})

    def set_dataset_status(self, status: str, error: str | None = None) -> None:
        with self._lock:
            set_dataset_status(self.db, self.bus, self.dataset_id, status, error)

    def check_cancel(self) -> None:
        with self._lock:
            flag = self.db.execute("SELECT cancel_requested FROM jobs WHERE id = ?", (self.id,)).fetchone()[0]
        if flag:
            raise JobCancelled()

    def finish(self, status: str, result: dict | None = None, error: str | None = None) -> None:
        with self._lock:
            progress = _progress(get_job(self.db, self.id))
            if status == "done":
                progress = {**progress, "pct": 100}
            self.db.execute(
                "UPDATE jobs SET status = ?, result_json = ?, error = ?, finished_at = ?, progress_json = ? WHERE id = ?",
                (status, json.dumps(result) if result is not None else None, error, now_iso(),
                 json.dumps(progress), self.id),
            )
            row = get_job(self.db, self.id)
            if status != "done":
                _failure_hook(self.db, self.bus, row, error or "")
            _end_event(self.db, self.bus, row)


class JobRunner:
    def __init__(self, settings: Settings, bus: EventBus, cache: VersionConnections) -> None:
        self.settings = settings
        self.bus = bus
        self.cache = cache
        self.owner = f"{socket.gethostname()}:{os.getpid()}:{ulid()}"
        self._loop: asyncio.AbstractEventLoop | None = None
        self._wake: asyncio.Event | None = None
        self._tasks: list[asyncio.Task] = []
        self._sweep: asyncio.Task | None = None
        self._stopping = False
        self._starts = 0  # nested lifespans of one app (tests) share one set of workers

    # --- lifecycle -------------------------------------------------------------------------

    async def start(self) -> None:
        self._starts += 1
        if self._starts > 1:
            return
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        self._stopping = False
        await asyncio.to_thread(self._recover)
        self._tasks = [asyncio.create_task(self._worker(), name=f"job-worker-{i}") for i in range(self.settings.job_workers)]
        self._sweep = asyncio.create_task(self._sweeper(), name="job-sweeper")

    async def stop(self) -> None:
        """Let running jobs finish for a few seconds; anything still running is re-queued next start."""
        self._starts -= 1
        if self._starts > 0:
            return
        self._stopping = True
        if self._wake is not None:
            self._wake.set()
        if self._sweep is not None:
            self._sweep.cancel()
            await asyncio.gather(self._sweep, return_exceptions=True)
            self._sweep = None
        if self._tasks:
            _, pending = await asyncio.wait(self._tasks, timeout=STOP_GRACE_S)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        self._tasks = []

    def wake(self) -> None:
        """Thread-safe: tell idle workers a job was queued."""
        if self._loop is not None and self._wake is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._wake.set)

    def enqueue(
        self, db: sqlite3.Connection, user_id: str, dataset_id: str | None, kind: str, params: dict | None = None
    ) -> sqlite3.Row:
        row = insert_job(db, user_id, dataset_id, kind, params)
        self.wake()
        return row

    # --- recovery --------------------------------------------------------------------------

    def _recover(self) -> None:
        db = connect(self.settings)
        try:
            # A job the user cancelled while it ran is cancelled, not run again, and its kind's hook
            # tidies up after it (cards left updating, a run left running).
            stopped = db.execute(
                "UPDATE jobs SET status = 'cancelled', error = 'Cancelled.', finished_at = ?, owner_pid = NULL "
                "WHERE status = 'running' AND cancel_requested = 1 AND (owner_pid IS NULL OR owner_pid != ?) RETURNING *",
                (now_iso(), self.owner),
            ).fetchall()
            for row in stopped:
                _failure_hook(db, self.bus, row, "Cancelled.")
                _end_event(db, self.bus, row)
            requeued = db.execute(
                "UPDATE jobs SET status = 'queued', owner_pid = NULL, heartbeat_at = NULL "
                "WHERE status = 'running' AND (owner_pid IS NULL OR owner_pid != ?)",
                (self.owner,),
            ).rowcount
            # Datasets imported while no profile job could run (e.g. before jobs existed).
            orphans = db.execute(
                "SELECT id, user_id FROM datasets d WHERE status = 'profiling' AND deleted_at IS NULL "
                "AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.dataset_id = d.id AND j.kind = 'profile' "
                "AND j.status IN ('queued', 'running'))"
            ).fetchall()
            for row in orphans:
                insert_job(db, row["user_id"], row["id"], "profile")
            if requeued or orphans or stopped:
                log.info("jobs: re-queued %d running job(s), cancelled %d, queued %d profile job(s)", requeued, len(stopped),
                         len(orphans))
        finally:
            db.close()

    def _requeue_stale(self) -> int:
        db = connect(self.settings)
        try:
            return db.execute(
                "UPDATE jobs SET status = 'queued', owner_pid = NULL, heartbeat_at = NULL "
                "WHERE status = 'running' AND owner_pid != ? AND heartbeat_at < ?",
                (self.owner, _ago(STALE_S)),
            ).rowcount
        finally:
            db.close()

    async def _sweeper(self) -> None:
        last_purge = 0.0
        while True:
            await asyncio.sleep(SWEEP_S)
            try:
                if await asyncio.to_thread(self._requeue_stale):
                    self.wake()
                interval = self.settings.purge_interval_s
                if interval > 0 and self.settings.job_workers > 0 and self._loop.time() - last_purge >= interval:
                    last_purge = self._loop.time()
                    if await asyncio.to_thread(self._queue_purge):
                        self.wake()
            except sqlite3.Error:
                log.exception("jobs: sweep failed")

    def _queue_purge(self) -> bool:
        """One purge job at a time (Schema §6): the first sweep after a start, then every interval."""
        db = connect(self.settings)
        try:
            if db.execute("SELECT 1 FROM jobs WHERE kind = 'purge' AND status IN ('queued', 'running')").fetchone():
                return False
            insert_job(db, "system", None, "purge", {})
            return True
        finally:
            db.close()

    # --- workers ---------------------------------------------------------------------------

    def _claim(self) -> sqlite3.Row | None:
        db = connect(self.settings)
        try:
            now = now_iso()
            # One statement, so no job runs twice; a queued cascade, stories or build waits while one of
            # those runs for its dataset (SERIAL_KINDS).
            rows = db.execute(
                "UPDATE jobs SET status = 'running', owner_pid = ?, heartbeat_at = ?, started_at = coalesce(started_at, ?) "
                "WHERE id = (SELECT q.id FROM jobs q WHERE q.status = 'queued' AND NOT ("
                f"q.kind IN ({_SERIAL}) AND q.dataset_id IS NOT NULL AND EXISTS (SELECT 1 FROM jobs r WHERE "
                f"r.dataset_id = q.dataset_id AND r.status = 'running' AND r.kind IN ({_SERIAL}))) "
                "ORDER BY q.created_at, q.id LIMIT 1) RETURNING *",
                (self.owner, now, now),
            ).fetchall()
            return rows[0] if rows else None
        finally:
            db.close()

    async def _worker(self) -> None:
        while not self._stopping:
            self._wake.clear()
            try:
                row = await asyncio.to_thread(self._claim)
            except sqlite3.Error:
                log.exception("jobs: claim failed")
                row = None
            if row is None:
                try:
                    await asyncio.wait_for(self._wake.wait(), POLL_S)
                except TimeoutError:
                    pass
                continue
            try:
                await self._run(row)
            except Exception:
                log.exception("jobs: job %s could not be finished", row["id"])

    async def _heartbeat(self, job_id: str) -> None:
        while True:
            await asyncio.sleep(HEARTBEAT_S)
            await asyncio.to_thread(self._beat, job_id)

    def _beat(self, job_id: str) -> None:
        db = connect(self.settings)
        try:
            db.execute("UPDATE jobs SET heartbeat_at = ? WHERE id = ? AND status = 'running'", (now_iso(), job_id))
        finally:
            db.close()

    async def _run(self, row: sqlite3.Row) -> None:
        ctx = await asyncio.to_thread(JobContext, self, row)
        heartbeat = asyncio.create_task(self._heartbeat(ctx.id))
        try:
            kind = HANDLERS.get(ctx.kind)
            if kind is None:
                raise RuntimeError(f"No handler for {ctx.kind} jobs yet.")
            result = await kind.run(ctx)
        except JobCancelled:
            await asyncio.to_thread(ctx.finish, "cancelled", None, "Cancelled.")
        except Exception as exc:
            log.exception("job %s (%s) failed", ctx.id, ctx.kind)
            message = str(exc).strip().splitlines()[0][:500] if str(exc).strip() else type(exc).__name__
            await asyncio.to_thread(ctx.finish, "failed", None, message)
        else:
            await asyncio.to_thread(ctx.finish, "done", result)
        finally:
            heartbeat.cancel()
            await asyncio.to_thread(ctx.close)
