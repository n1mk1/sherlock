"""A version on every chat message (TRD §8.1, §4.9, Schema §2.15–2.16): history lines say the version
they were written on, Add to Flow refuses an answer from an older version, `update_widget` keeps the rest of
the widget's spec, and a selection is counted on the current version. Recorded replies: `chat_titanic.json`
and `chat_actions.json`."""

import shutil
import sqlite3
from pathlib import Path

import pytest

from sherlock.agent.answerers import merged_spec
from sherlock.config import get_settings
from sherlock.db import migrate as mig
from sherlock.llm import fixtures
from sherlock.llm.schemas import WidgetDraft
from tests.test_chat import blocks_of, send
from tests.test_jobs import wait_status

API = "/api/v1"
LLM = Path(__file__).parent / "fixtures" / "llm"
pytestmark = pytest.mark.usefixtures("run_jobs")


@pytest.fixture(autouse=True)
def mocked(monkeypatch, tmp_path):
    folder = tmp_path / "llm"
    folder.mkdir()
    for name in ("chat_titanic.json", "chat_actions.json"):
        shutil.copy(LLM / name, folder / name)
    monkeypatch.setenv("LLM_MOCK", str(folder))
    get_settings.cache_clear()


@pytest.fixture
def prompts(monkeypatch) -> list:
    """Every prompt the recorded model is asked, as (purpose, prompt)."""
    transports = []
    load = fixtures.FixtureTransport.load.__func__

    def keep(cls, path):
        transports.append(load(cls, path))
        return transports[-1]

    monkeypatch.setattr(fixtures.FixtureTransport, "load", classmethod(keep))
    return transports


@pytest.fixture
def ready(client):
    ds = client.post(f"{API}/datasets/sample").json()
    wait_status(client, ds["id"], "offer")
    client.post(f"{API}/datasets/{ds['id']}/use-as-is")
    wait_status(client, ds["id"], "ready")
    return client.get(f"{API}/datasets/{ds['id']}").json()


def edit(client, ds: dict, row_id: int, column: str, value: str) -> int:
    """One cell edit through the grid's save; returns the new version."""
    v = client.get(f"{API}/datasets/{ds['id']}").json()["current_version"]
    r = client.post(f"{API}/datasets/{ds['id']}/edits", json={"base_version": v, "edits": [
        {"row_id": row_id, "column": column, "value": value}]})
    assert r.status_code == 201, r.text
    return r.json()["version"]


def test_an_answer_keeps_its_version_and_an_older_one_stays_off_the_canvas(client, ready, prompts):
    ds, v = ready["id"], ready["current_version"]
    _, msg = send(client, ds, "average fare by class")
    assert msg["version"] == v
    flow = next(a for a in msg["actions"] if a["kind"] == "add_to_flow")
    assert edit(client, ready, 1, "fare", "100") == v + 1

    thread = client.get(f"{API}/datasets/{ds}/chat").json()
    assert [m["version"] for m in thread] == [v, v]
    assert not any(a["kind"] == "add_to_flow" for a in thread[1]["actions"])  # Add to Flow isn't offered any more
    r = client.post(f"{API}/messages/{msg['id']}/pin", json={"target": "flow", "block_index": flow["block_index"]})
    assert r.status_code == 409 and f"worked out on version {v}" in r.json()["error"]["message"]

    # The next message's history says which version each line was written on.
    _, follow = send(client, ds, "and for women only?")
    assert follow["version"] == v + 1
    route = next(p["prompt"] for t in prompts for p in t.calls if p["purpose"] == "route" and "women only" in p["prompt"])
    assert f"[v{v}] user: average fare by class" in route and f"[v{v}] assistant: First class paid" in route
    flow = next(a for a in follow["actions"] if a["kind"] == "add_to_flow")
    assert client.post(f"{API}/messages/{follow['id']}/pin", json={"target": "flow", "block_index": flow["block_index"]}).status_code == 201


def test_update_widget_keeps_the_rest_of_the_spec(client, ready):
    ds = ready["id"]
    w = client.post(f"{API}/datasets/{ds}/widgets", json={
        "scope": {"rows": {"predicate": "pclass = 1", "inherit_global_filters": False}},
        "op": {"type": "sql", "sql": "SELECT sex, AVG(fare) AS avg_fare FROM t WHERE {{rows}} GROUP BY 1 ORDER BY 1"},
        "view": {"type": "bar", "options": {"x": "sex", "y": "avg_fare", "sort": "desc"}}, "title": "Fare by sex"})
    assert w.status_code == 201, w.text
    wid = w.json()["widget"]["id"]
    send(client, ds, "make it a pie chart", context={"tab": "dashboard", "focused_widget_id": wid})
    spec = next(x for x in client.get(f"{API}/datasets/{ds}/widgets").json()["widgets"] if x["id"] == wid)["spec"]
    options = {k: v for k, v in spec["view"]["options"].items() if k != "undo_title"}  # the service's own, for Undo
    assert spec["view"]["type"] == "pie" and options == {"x": "sex", "y": "avg_fare", "sort": "desc"}
    assert spec["scope"]["rows"]["predicate"] == "pclass = 1" and spec["scope"]["rows"]["inherit_global_filters"] is False
    data = client.get(f"{API}/widgets/{wid}/data").json()
    assert sum(r[1] > 0 for r in data["rows"]) == 2  # first class only: the predicate still applies


def test_merged_spec():
    old = {"scope": {"columns": {"x": "a", "y": "b", "series": "s"}, "rows": {"predicate": "p", "selection_id": "sel_1",
                                                                              "inherit_global_filters": False}},
           "op": {"type": "sql", "sql": "old"}, "view": {"type": "bar", "options": {"x": "a", "y": "b", "colors": ["c"]}}}
    kpi = WidgetDraft(reading="", title="", sql="new", view="kpi", x=None, y="total")
    new = merged_spec(old, kpi)
    assert new["op"] == {"type": "sql", "sql": "new"} and new["view"] == {"type": "kpi", "options": {"colors": ["c"], "value": "total"}}
    assert new["scope"]["rows"] == old["scope"]["rows"] and new["scope"]["columns"] == {"x": None, "y": "total", "series": "s"}
    assert old["op"]["sql"] == "old"  # the widget's own spec isn't changed in place


def test_a_selection_is_counted_on_the_current_version(client, ready):
    ds = ready["id"]
    _, msg = send(client, ds, "which passengers paid more than 500?")
    table = blocks_of(msg, "table")[0]
    assert table["total"] == 4
    edit(client, ready, table["rows"][0][0], "fare", "100")  # one of the four now paid less
    _, msg = send(client, ds, "clean these rows", context={"tab": "csv", "selection_id": table["selection_id"]})
    assert msg["proposal"]["summary"] == "Clean with AI on the 3 selected rows"
    assert msg["proposal"]["impact"]["rows_affected"] == 3
    plan = client.post(f"{API}/datasets/{ds}/clean/plan", json={"scope": {"kind": "selection", "selection_id": table["selection_id"]}})
    assert plan.status_code in (200, 201), plan.text
    assert plan.json()["scope"]["rows"] == 3


def test_the_migration_gives_older_messages_their_version(tmp_path, monkeypatch):
    conn = sqlite3.connect(tmp_path / "db.sqlite")
    conn.row_factory = sqlite3.Row
    every = mig.available()
    monkeypatch.setattr(mig, "available", lambda: [m for m in every if m[0] < 6])
    mig.migrate(conn)
    conn.execute("INSERT INTO users (id, cookie_token, created_at, last_seen_at) VALUES ('u', 't', 'x', 'x')")
    conn.execute("INSERT INTO datasets (id, user_id, name, original_filename, status, import_options_json, expires_at, "
                 "created_at) VALUES ('d', 'u', 'n', 'n.csv', 'ready', '{}', 'z', '2026-10-01')")
    for v, at in ((1, "2026-10-01T10:00"), (2, "2026-10-01T12:00")):
        conn.execute("INSERT INTO versions (dataset_id, version, parquet_path, row_count, column_count, columns_json, "
                     "created_at) VALUES ('d', ?, 'p', 1, 1, '[]', ?)", (v, at))
    for mid, at in (("m0", "2026-10-01T09:00"), ("m1", "2026-10-01T11:00"), ("m2", "2026-10-01T13:00")):
        conn.execute("INSERT INTO messages (id, dataset_id, role, text, created_at) VALUES (?, 'd', 'user', 'q', ?)", (mid, at))
    conn.commit()
    monkeypatch.setattr(mig, "available", lambda: every)
    assert 6 in mig.migrate(conn)
    got = {r["id"]: r["version"] for r in conn.execute("SELECT id, version FROM messages")}
    assert got == {"m0": None, "m1": 1, "m2": 2}
    conn.close()
