"""Checkpoints with resume and the purge job (Implementation Plan D8.6; TRD §3.3; Schema §6)."""

import json
import os
import time
from datetime import UTC, datetime, timedelta

import pytest

from sherlock.config import get_settings
from sherlock.db.connection import connect
from sherlock.db.util import new_id, now_iso
from sherlock.jobs.purge import purge
from sherlock.sandbox.runner import sandbox_root
from sherlock.storage import dataset_dir
from tests.test_jobs import db_rows, upload, wait_for

API = "/api/v1"


def ago(seconds: float) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def run_purge():
    settings = get_settings()
    db = connect(settings)
    try:
        return purge(settings, db, None)
    finally:
        db.close()


def test_purge_removes_what_is_past_its_time_and_keeps_the_rest(client):
    settings = get_settings()
    old = upload(client, b"a,b\n1,2\n")["id"]
    kept = upload(client, b"a,b\n3,4\n")["id"]
    expiring = upload(client, b"a,b\n5,6\n")["id"]
    user = db_rows("SELECT user_id FROM datasets WHERE id = ?", old)[0]["user_id"]
    folder = dataset_dir(settings, user, old)
    assert folder.is_dir()
    db_rows("UPDATE datasets SET deleted_at = ? WHERE id = ?", ago(1200), old)          # deleted 20 min ago: goes
    db_rows("UPDATE datasets SET deleted_at = ? WHERE id = ?", ago(60), kept)           # 1 min ago: can still be restored
    db_rows("UPDATE datasets SET expires_at = ? WHERE id = ?", ago(10), expiring)        # past its 7 days: soft-deleted
    db_rows("INSERT INTO job_events (dataset_id, type, data_json, created_at) VALUES (?, 'x', '{}', ?)", kept, ago(90000))
    db_rows("INSERT INTO llm_calls (user_id, dataset_id, role, model, purpose, ok, created_at) "
            "VALUES (?, ?, 'small', 'm', 'purge-test', 1, ?)", user, old, ago(1200))
    stale = sandbox_root(settings) / "old-run"
    stale.mkdir(parents=True, exist_ok=True)
    os.utime(stale, (time.time() - 7200, time.time() - 7200))

    counts = run_purge()
    assert counts["datasets"] == 1 and counts["expired"] == 1 and counts["events"] >= 1 and counts["sandbox_dirs"] == 1
    assert not db_rows("SELECT 1 FROM datasets WHERE id = ?", old) and not folder.exists()
    assert not db_rows("SELECT 1 FROM job_events WHERE dataset_id = ?", old)
    assert db_rows("SELECT 1 FROM llm_calls WHERE purpose = 'purge-test'")  # spend accounting stays
    assert db_rows("SELECT deleted_at FROM datasets WHERE id = ?", kept)[0]["deleted_at"]  # still restorable
    assert client.post(f"{API}/datasets/{kept}/restore").status_code == 200
    assert db_rows("SELECT deleted_at FROM datasets WHERE id = ?", expiring)[0]["deleted_at"]
    assert not stale.exists()
    used = db_rows("SELECT storage_bytes FROM users WHERE id = ?", user)[0]["storage_bytes"]
    live = db_rows("SELECT sum(folder_bytes) AS n FROM datasets WHERE user_id = ?", user)[0]["n"]
    assert used == live > 0


def test_purge_drops_old_deleted_widgets_and_cards_and_old_exports(client):
    ds = upload(client, b"a,b\n1,2\n3,4\n")["id"]
    now = now_iso()
    for wid, deleted in (("wgt_old", ago(1200)), ("wgt_new", ago(30))):
        db_rows("INSERT INTO widgets (id, dataset_id, spec_json, spec_hash, title, status, version_built, created_by, order_no, "
                "created_at, updated_at, deleted_at) VALUES (?, ?, '{}', 'h', 't', 'ready', 1, 'user', 0, ?, ?, ?)",
                wid, ds, now, now, deleted)
        db_rows("INSERT INTO cards (id, dataset_id, kind, widget_id, headline_json, body_json, status, version, created_at, "
                "updated_at) VALUES (?, ?, 'widget', ?, '{}', '{}', 'ready', 1, ?, ?)", f"crd_{wid}", ds, wid, now, now)
    db_rows("INSERT INTO exports (id, dataset_id, kind, version, options_json, cache_key, status, path, created_at) "
            "VALUES ('exp_old', ?, 'notebook', 1, '{}', 'k', 'done', 'exports/notebook_k.ipynb', ?)", ds, ago(90000))
    counts = run_purge()
    assert counts["widgets"] == 1 and counts["exports"] == 1
    assert [r["id"] for r in db_rows("SELECT id FROM widgets WHERE dataset_id = ?", ds)] == ["wgt_new"]
    assert [r["id"] for r in db_rows("SELECT id FROM cards WHERE dataset_id = ?", ds)] == ["crd_wgt_new"]
    assert not db_rows("SELECT 1 FROM exports WHERE id = 'exp_old'")


def test_purge_drops_idle_empty_workspaces_and_left_over_cleaning_folders(client):
    settings = get_settings()
    ds = upload(client, b"a,b\n1,2\n")["id"]
    owner = db_rows("SELECT user_id FROM datasets WHERE id = ?", ds)[0]["user_id"]
    for uid, seen in (("usr_idle", ago(90000)), ("usr_recent", ago(60))):  # a cookie-less visitor a day ago, one just now
        db_rows("INSERT INTO users (id, cookie_token, created_at, last_seen_at) VALUES (?, ?, ?, ?)", uid, uid, seen, seen)
    db_rows("UPDATE users SET last_seen_at = ? WHERE id = ?", ago(90000), owner)  # idle too, but has a CSV
    work = settings.data_dir / ".clean"
    for name in ("job_crashed", "job_live"):
        (work / name).mkdir(parents=True)
        os.utime(work / name, (time.time() - 7200, time.time() - 7200))
    db_rows("INSERT INTO jobs (id, dataset_id, user_id, kind, status, created_at) VALUES ('job_live', ?, ?, 'clean', 'running', ?)",
            ds, owner, now_iso())

    counts = run_purge()
    assert counts["users"] == 1 and counts["clean_dirs"] == 1
    assert {r["id"] for r in db_rows("SELECT id FROM users")} == {owner, "usr_recent"}
    assert not (work / "job_crashed").exists() and (work / "job_live").is_dir()


def test_the_runner_queues_one_purge_at_a_time(client):
    runner = client.app.state.jobs
    assert runner._queue_purge() is True
    assert runner._queue_purge() is False  # one is already queued
    job = db_rows("SELECT * FROM jobs WHERE kind = 'purge'")
    assert len(job) == 1 and job[0]["user_id"] == "system" and job[0]["dataset_id"] is None


@pytest.fixture
def mocked(monkeypatch):
    from tests.test_stories import FIXTURE

    monkeypatch.setenv("LLM_MOCK", str(FIXTURE))
    get_settings.cache_clear()


@pytest.mark.usefixtures("run_jobs")
def test_a_requeued_stories_job_resumes_from_its_checkpoint(mocked, client):
    from tests.test_stories import _ready_with_stories

    ds = _ready_with_stories(client)
    widgets = [w["id"] for w in client.get(f"{API}/datasets/{ds}/widgets").json()["widgets"]]
    sql = [w["id"] for w in client.get(f"{API}/datasets/{ds}/widgets").json()["widgets"] if w["spec"]["op"]["type"] == "sql"]
    left = sql[-1]
    told = [w for w in widgets if w != left]
    # As if the process stopped after storing every card but the last: the job comes back queued with its state.
    job_id = new_id("job")
    user = db_rows("SELECT user_id FROM datasets WHERE id = ?", ds)[0]["user_id"]
    db_rows("INSERT INTO jobs (id, dataset_id, user_id, kind, status, params_json, state_json, created_at) "
            "VALUES (?, ?, ?, 'stories', 'queued', ?, ?, ?)", job_id, ds, user,
            json.dumps({"widget_ids": None, "reason": "refresh"}), json.dumps({"told": told}), now_iso())
    client.app.state.jobs.wake()
    done = wait_for(lambda: (j := client.get(f"{API}/jobs/{job_id}").json())["status"] in ("done", "failed") and j, timeout=60)
    assert done["status"] == "done" and done["result"]["widgets"] == 1, done
    state = json.loads(db_rows("SELECT state_json FROM jobs WHERE id = ?", job_id)[0]["state_json"])
    assert set(state["told"]) == set(widgets) and left in state["told"]
