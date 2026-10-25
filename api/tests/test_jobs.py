import asyncio
import json
import threading
import time

import httpx2
import pytest
import uvicorn
from fastapi.testclient import TestClient

from sherlock.config import get_settings
from sherlock.db.connection import connect
from sherlock.jobs import runner as runner_mod
from sherlock.jobs.events import Event, EventBus
from sherlock.jobs.runner import HANDLERS, JobKind
from sherlock.main import create_app
from sherlock.profile import service as profile_service
from sherlock.routers import streams

API = "/api/v1"
pytestmark = pytest.mark.usefixtures("run_jobs")
CSV = b"name,age,fare\nAnn,30,7.25\nBob,,8.05\nCy,41,-1\nDee,29,100\n"
# All text, so the profile job commits no typing step: the event-sequence tests stay about the runner.
TEXT_CSV = b"name,city\nAnn,Paris\nBob,Lyon\nCy,Nice\n"


def upload(client, content: bytes = CSV, filename="data.csv"):
    r = client.post(f"{API}/datasets", files={"file": (filename, content, "text/csv")})
    assert r.status_code == 201, r.text
    return r.json()


def wait_for(fn, timeout=20.0, interval=0.15):
    # 0.15 s keeps a long wait under the 600 reads a minute rate limit (TRD §15); at 0.05 s a wait past
    # 30 s on a busy machine started getting 429s.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("timed out waiting")


def wait_status(client, dataset_id, *statuses):
    return wait_for(lambda: (d := client.get(f"{API}/datasets/{dataset_id}").json())["status"] in statuses and d)


def db_rows(sql, *params):
    conn = connect(get_settings())
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def events_of(dataset_id):
    return [(r["type"], json.loads(r["data_json"])) for r in db_rows(
        "SELECT type, data_json FROM job_events WHERE dataset_id = ? ORDER BY id", dataset_id)]


# --- the profile job ---------------------------------------------------------------------


def test_upload_queues_profile_job_that_ends_in_offer(client):
    ds = upload(client)
    assert ds["status"] == "profiling"
    done = wait_status(client, ds["id"], "offer", "failed")
    assert done["status"] == "offer"

    # The typing step made version 2, and the job built its card before any request asked for it.
    assert done["current_version"] == 2
    assert db_rows("SELECT 1 FROM datacards WHERE dataset_id = ? AND version = 2", ds["id"])
    jobs = client.get(f"{API}/jobs", params={"dataset_id": ds["id"]}).json()
    assert [j["kind"] for j in jobs] == ["profile"]
    job = jobs[0]
    assert job["status"] == "done" and job["progress"]["pct"] == 100
    assert job["progress"]["label"] == "Profiling 3 columns"
    assert job["result"]["version"] == 2 and job["result"]["issues"] >= 1 and job["result"]["typing_step_id"]
    assert job["started_at"] and job["finished_at"]
    card = client.get(f"{API}/datasets/{ds['id']}/datacard").json()
    assert len(card["issues"]) == job["result"]["issues"]

    types = [t for t, _ in events_of(ds["id"])]
    assert types == ["job.progress", "version.created", "job.log", "job.progress", "dataset.status", "job.done"]
    _, status = events_of(ds["id"])[4]
    assert status == {"dataset_id": ds["id"], "status": "offer", "current_version": 2}


def test_sample_is_profiled(client):
    r = client.post(f"{API}/datasets/sample")
    assert r.status_code == 201
    assert wait_status(client, r.json()["id"], "offer", "failed")["status"] == "offer"
    # Asking again returns the same sample and queues nothing new.
    again = client.post(f"{API}/datasets/sample")
    assert again.status_code == 200
    assert len(client.get(f"{API}/jobs", params={"dataset_id": r.json()["id"]}).json()) == 1


def test_failed_profile_marks_dataset_failed_and_retry_recovers(client, monkeypatch):
    real = profile_service.get_or_build

    def boom(*args, **kwargs):
        raise RuntimeError("disk on fire\nsecond line")

    monkeypatch.setattr(profile_service, "get_or_build", boom)
    ds = upload(client)
    failed = wait_status(client, ds["id"], "failed", "offer")
    assert failed["status"] == "failed" and failed["error"] == "disk on fire"
    job = client.get(f"{API}/jobs", params={"dataset_id": ds["id"]}).json()[0]
    assert job["status"] == "failed" and job["error"] == "disk on fire"
    assert [t for t, _ in events_of(ds["id"])][-2:] == ["dataset.status", "job.failed"]

    monkeypatch.setattr(profile_service, "get_or_build", real)
    r = client.post(f"{API}/jobs/{job['id']}/retry")
    assert r.status_code == 201 and r.json()["id"] != job["id"] and r.json()["kind"] == "profile"
    assert wait_status(client, ds["id"], "offer")["error"] is None
    # A done job can't be retried.
    assert client.post(f"{API}/jobs/{r.json()['id']}/retry").status_code == 409


def test_concurrent_datacard_request_waits_for_the_job(client):
    ds = upload(client, TEXT_CSV)
    card = client.get(f"{API}/datasets/{ds['id']}/datacard").json()
    wait_status(client, ds["id"], "offer")
    assert client.get(f"{API}/datasets/{ds['id']}/datacard").json() == card
    assert len(db_rows("SELECT id FROM issues WHERE dataset_id = ?", ds["id"])) == len(card["issues"])


# --- runner: cancel, unknown kinds, logs, recovery -----------------------------------------


@pytest.fixture
def no_workers(monkeypatch):
    monkeypatch.setenv("JOB_WORKERS", "0")
    get_settings.cache_clear()


def test_cancel_queued_job(no_workers):
    with TestClient(create_app()) as client:
        ds = upload(client)
        job = client.get(f"{API}/jobs", params={"dataset_id": ds["id"]}).json()[0]
        assert job["status"] == "queued"
        assert client.post(f"{API}/jobs/{job['id']}/cancel").status_code == 204
        job = client.get(f"{API}/jobs/{job['id']}").json()
        assert job["status"] == "cancelled" and job["finished_at"]
        assert client.get(f"{API}/datasets/{ds['id']}").json()["status"] == "failed"
        assert [t for t, _ in events_of(ds["id"])] == ["dataset.status", "job.failed"]
        # Idempotent.
        assert client.post(f"{API}/jobs/{job['id']}/cancel").status_code == 204


def _start(client, dataset_id, kind):
    app = client.app
    conn = connect(app.state.settings)
    try:
        user_id = conn.execute("SELECT user_id FROM datasets WHERE id = ?", (dataset_id,)).fetchone()[0]
        return app.state.jobs.enqueue(conn, user_id, dataset_id, kind)["id"]
    finally:
        conn.close()


def test_cancel_running_job_and_log(client, monkeypatch):
    async def endless(ctx):
        await asyncio.to_thread(ctx.log, "looking at age", icon="search", column="age")
        while True:
            await asyncio.to_thread(ctx.check_cancel)
            await asyncio.sleep(0.02)

    monkeypatch.setitem(HANDLERS, "stories", JobKind(endless))
    ds = upload(client)
    wait_status(client, ds["id"], "offer")
    job_id = _start(client, ds["id"], "stories")
    wait_for(lambda: client.get(f"{API}/jobs/{job_id}").json()["status"] == "running")
    assert client.post(f"{API}/jobs/{job_id}/cancel").status_code == 204
    job = wait_for(lambda: (j := client.get(f"{API}/jobs/{job_id}").json())["status"] == "cancelled" and j)
    assert job["error"] == "Cancelled."
    assert client.get(f"{API}/datasets/{ds['id']}").json()["status"] == "offer"  # stories has no failure hook
    entries = client.get(f"{API}/jobs/{job_id}/log").json()["entries"]
    assert [(e["text"], e["icon"], e["column"]) for e in entries] == [("looking at age", "search", "age")]
    assert events_of(ds["id"])[-1][0] == "job.failed"


def test_kind_without_handler_fails(client):
    ds = upload(client)
    wait_status(client, ds["id"], "offer")
    job_id = _start(client, ds["id"], "undo")  # undo runs in the request, so the kind has no job handler
    job = wait_for(lambda: (j := client.get(f"{API}/jobs/{job_id}").json())["status"] == "failed" and j)
    assert "No handler" in job["error"]


def test_startup_requeues_orphans(no_workers, monkeypatch):
    with TestClient(create_app()) as client:
        first = upload(client)
        second = upload(client)
        cookies = dict(client.cookies)
    conn = connect(get_settings())
    try:
        # The first job was running in a process that died; the second dataset lost its job entirely.
        conn.execute("UPDATE jobs SET status = 'running', owner_pid = 'gone:1:x', heartbeat_at = '2000-01-01T00:00:00.000Z' "
                     "WHERE dataset_id = ?", (first["id"],))
        conn.execute("DELETE FROM jobs WHERE dataset_id = ?", (second["id"],))
    finally:
        conn.close()
    monkeypatch.setenv("JOB_WORKERS", "2")
    get_settings.cache_clear()
    with TestClient(create_app(), cookies=cookies) as client:
        for ds in (first, second):
            assert wait_status(client, ds["id"], "offer", "failed")["status"] == "offer"


def test_sweeper_requeues_stale_jobs(client, monkeypatch):
    ds = upload(client)
    wait_status(client, ds["id"], "offer")
    conn = connect(get_settings())
    try:
        conn.execute("UPDATE jobs SET status = 'running', owner_pid = 'other:2:y', heartbeat_at = '2000-01-01T00:00:00.000Z'")
    finally:
        conn.close()
    assert client.app.state.jobs._requeue_stale() == 1
    client.app.state.jobs.wake()
    wait_for(lambda: client.get(f"{API}/jobs", params={"dataset_id": ds["id"]}).json()[0]["status"] == "done")


def test_jobs_are_owned(client, app):
    ds = upload(client)
    job = client.get(f"{API}/jobs", params={"dataset_id": ds["id"]}).json()[0]
    other = TestClient(app)  # a second user; no second lifespan, so one runner
    assert other.get(f"{API}/jobs/{job['id']}").status_code == 404
    assert other.post(f"{API}/jobs/{job['id']}/cancel").status_code == 404
    assert other.get(f"{API}/jobs/{job['id']}/log").status_code == 404
    assert other.get(f"{API}/jobs", params={"dataset_id": ds["id"]}).status_code == 404
    assert other.get(f"{API}/jobs").json() == []
    assert other.get(f"{API}/datasets/{ds['id']}/events").status_code == 404
    assert [j["id"] for j in client.get(f"{API}/jobs").json()] == [job["id"]]


# --- the event bus -------------------------------------------------------------------------


def test_bus_publishes_across_threads_to_matching_subscribers():
    async def main():
        bus = EventBus()
        mine = bus.subscribe(lambda e: e.dataset_id == "ds_a")
        bus.subscribe(lambda e: False)
        events = [Event(i, "ds_a" if i % 2 else "ds_b", "usr_1", "job.progress", {}) for i in range(1, 7)]
        threads = [threading.Thread(target=bus.publish, args=(e,)) for e in events]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        got = sorted([(await asyncio.wait_for(mine.queue.get(), 1)).id for _ in range(3)])
        assert got == [1, 3, 5] and mine.queue.empty()
        bus.unsubscribe(mine)
        assert bus.subscriber_count == 1

    asyncio.run(main())


def test_sse_format():
    e = Event(7, "ds_a", "usr_1", "dataset.status", {"dataset_id": "ds_a", "status": "offer"})
    assert e.sse() == 'id: 7\nevent: dataset.status\ndata: {"dataset_id":"ds_a","status":"offer"}\n\n'


# --- SSE over a real server ----------------------------------------------------------------


@pytest.fixture
def live(app):
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="on"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    wait_for(lambda: server.started, timeout=15)
    port = server.servers[0].sockets[0].getsockname()[1]
    with httpx2.Client(base_url=f"http://127.0.0.1:{port}", timeout=10) as client:
        yield client
    server.should_exit = True
    thread.join(timeout=15)


def read_events(client, path, headers=None, until=lambda evs: False, timeout=10.0, keep_comments=False):
    """Read an SSE stream until `until(events)` holds; events are (id, type, data) or comments."""
    events, current = [], {}
    deadline = time.monotonic() + timeout
    with client.stream("GET", path, headers=headers or {}) as r:
        assert r.status_code == 200, r.read()
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith(":"):
                if keep_comments:
                    events.append(("comment", line))
            elif line.startswith("id: "):
                current["id"] = int(line[4:])
            elif line.startswith("event: "):
                current["type"] = line[7:]
            elif line.startswith("data: "):
                current["data"] = json.loads(line[6:])
            elif line == "" and current:
                events.append((current["id"], current["type"], current["data"]))
                current = {}
            if until(events) or time.monotonic() > deadline:
                break
    return events


def _types(events):
    return [e[1] for e in events if e[0] != "comment"]


def test_sse_live_then_replay(live, app):
    collected = []
    ds = live.post(f"{API}/datasets", files={"file": ("a.csv", TEXT_CSV, "text/csv")}).json()
    cookies = dict(live.cookies)
    wait_for(lambda: live.get(f"{API}/datasets/{ds['id']}").json()["status"] == "offer")

    # Replay from the start: everything the profile job emitted, in order, with increasing ids.
    replayed = read_events(live, f"{API}/datasets/{ds['id']}/events", {"Last-Event-ID": "0"},
                           until=lambda evs: "job.done" in _types(evs))
    assert _types(replayed) == ["job.progress", "job.progress", "dataset.status", "job.done"]
    ids = [e[0] for e in replayed]
    assert ids == sorted(ids)
    assert replayed[3][2]["status"] == "done" and replayed[2][2]["dataset_id"] == ds["id"]

    # Resume after the first event: only the later three come back.
    resumed = read_events(live, f"{API}/datasets/{ds['id']}/events", {"Last-Event-ID": str(ids[0])},
                          until=lambda evs: "job.done" in _types(evs))
    assert [e[0] for e in resumed] == ids[1:]
    # The query parameter works the same for a first connection.
    by_query = read_events(live, f"{API}/datasets/{ds['id']}/events?last_event_id={ids[1]}",
                           until=lambda evs: "job.done" in _types(evs))
    assert [e[0] for e in by_query] == ids[2:]

    # Live: a stream opened before a second upload sees the user-level events as they happen.
    def listen():
        with httpx2.Client(base_url=str(live.base_url), cookies=cookies, timeout=10) as c:
            collected.extend(read_events(c, f"{API}/events",
                                         until=lambda evs: any(e[1] == "dataset.status" for e in evs)))

    t = threading.Thread(target=listen)
    t.start()
    wait_for(lambda: app.state.bus.subscriber_count >= 1)
    second = live.post(f"{API}/datasets", files={"file": ("b.csv", TEXT_CSV, "text/csv")}).json()
    t.join(timeout=15)
    assert _types(collected) == ["job.progress", "job.progress", "dataset.status"]  # job.done isn't on the user stream
    assert all(e[2]["dataset_id"] == second["id"] for e in collected)


def test_user_stream_replay_filters_types(live):
    ds = live.post(f"{API}/datasets", files={"file": ("a.csv", TEXT_CSV, "text/csv")}).json()
    wait_for(lambda: live.get(f"{API}/datasets/{ds['id']}").json()["status"] == "offer")
    events = read_events(live, f"{API}/events", {"Last-Event-ID": "0"},
                         until=lambda evs: "dataset.status" in _types(evs))
    assert _types(events) == ["job.progress", "job.progress", "dataset.status"]


def test_sse_heartbeat(live, monkeypatch):
    monkeypatch.setattr(streams, "HEARTBEAT_S", 0.2)
    ds = live.post(f"{API}/datasets", files={"file": ("a.csv", CSV, "text/csv")}).json()
    wait_for(lambda: live.get(f"{API}/datasets/{ds['id']}").json()["status"] == "offer")
    events = read_events(live, f"{API}/datasets/{ds['id']}/events", keep_comments=True,
                         until=lambda evs: sum(1 for e in evs if e == ("comment", ": ping")) >= 2)
    assert sum(1 for e in events if e == ("comment", ": ping")) >= 2


def test_runner_constants_match_trd():
    assert runner_mod.HEARTBEAT_S == 10 and runner_mod.STALE_S == 60 and streams.HEARTBEAT_S == 15


@pytest.mark.usefixtures("run_jobs")
def test_a_save_cascades_to_every_widget_once(client):
    """Cascade v0 (TRD §7.6, D5.5): a commit re-queries every widget on the new version; saves
    within the debounce window share one cascade."""
    ds = client.post(f"{API}/datasets/sample").json()
    wait_status(client, ds["id"], "offer")
    client.post(f"{API}/datasets/{ds['id']}/use-as-is")
    d = wait_status(client, ds["id"], "ready")
    v = d["current_version"]
    a = client.post(f"{API}/datasets/{ds['id']}/edits",
                    json={"base_version": v, "edits": [{"row_id": 1, "column": "age", "value": "1"}]}).json()
    client.post(f"{API}/datasets/{ds['id']}/edits",
                json={"base_version": a["version"], "edits": [{"row_id": 2, "column": "age", "value": "2"}]})
    jobs = wait_for(lambda: (js := [j for j in client.get(f"{API}/jobs?dataset_id={ds['id']}").json()
                                    if j["kind"] == "cascade"]) and all(j["status"] == "done" for j in js) and js,
                    timeout=30)
    assert len(jobs) == 1 and jobs[0]["result"]["version"] == v + 2
    widgets = client.get(f"{API}/datasets/{ds['id']}/widgets").json()["widgets"]
    assert widgets and all(w["version_built"] == v + 2 for w in widgets)
    types = [r[0] for r in db_rows("SELECT type FROM job_events WHERE dataset_id = ? AND type LIKE 'cascade.%' ORDER BY id", ds["id"])]
    assert types == ["cascade.started", "cascade.done"]
