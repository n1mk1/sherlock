"""Chat completion (Implementation Plan D8.5; TRD §8.1 step 4, §8.2 actions; PRD ASK-7, ASK-10): proposals
for cell edits and cleaning with approve and reject, `update_widget`, a multi-step plan, and "export a
notebook" from chat. Recorded model replies (`chat_titanic.json` plus `chat_actions.json`)."""

import shutil
from pathlib import Path

import pytest

from sherlock.config import get_settings
from tests.test_chat import send
from tests.test_jobs import db_rows, events_of, wait_status

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
def ready(client):
    ds = client.post(f"{API}/datasets/sample").json()
    wait_status(client, ds["id"], "offer")
    client.post(f"{API}/datasets/{ds['id']}/use-as-is")
    wait_status(client, ds["id"], "ready")
    return client.get(f"{API}/datasets/{ds['id']}").json()


def csv(**context):
    return {"context": {"tab": "csv", **context}}


def test_cell_edits_arrive_as_a_proposal_and_apply_only_when_approved(client, ready):
    ds, v = ready["id"], ready["current_version"]
    events, msg = send(client, ds, "set the fare of row 1 to 100", **csv())
    p = msg["proposal"]
    assert ("proposal", p) in [(e, d) for e, d in events if e == "proposal"]
    assert p["kind"] == "edit_cells" and p["status"] == "pending" and p["base_version"] == v
    assert p["edits"] == [{"row_id": 1, "column": "fare", "value": "100", "before": pytest.approx(211.3375)}]
    assert p["impact"] == {"cells_changed": 1, "rows_affected": 1} and p["summary"] == "Change 1 cell in 1 row: fare"
    assert client.get(f"{API}/datasets/{ds}").json()["current_version"] == v  # nothing changed yet

    done = client.post(f"{API}/proposals/{p['id']}/approve", json={})
    assert done.status_code == 200, done.text
    assert done.json()["version"] == v + 1
    rows = client.get(f"{API}/datasets/{ds}/rows?limit=1").json()
    assert rows["rows"][0]["cells"]["fare"] == 100
    again = client.post(f"{API}/proposals/{p['id']}/approve", json={})
    assert again.status_code == 409 and "already approved" in again.json()["error"]["message"]
    thread = client.get(f"{API}/datasets/{ds}/chat").json()
    assert thread[-1]["proposal"]["status"] == "approved" and thread[-1]["proposal"]["result_step_id"]

    # A proposal computed on an older version expires instead of applying.
    _, old = send(client, ds, "set the fare of row 1 to 100", **csv())
    assert "nothing to change" in old["text"]  # row 1 already holds 100: no proposal at all
    _, stale = send(client, ds, "clean these rows", **csv(selected_cells={"row_ids": [1, 2, 3], "columns": ["age"]}))
    client.post(f"{API}/datasets/{ds}/edits", json={"base_version": v + 1, "edits": [{"row_id": 2, "column": "fare", "value": "1"}]})
    gone = client.post(f"{API}/proposals/{stale['proposal']['id']}/approve", json={})
    assert gone.status_code == 409 and client.get(f"{API}/proposals/{stale['proposal']['id']}").json()["status"] == "expired"


def test_a_clean_proposal_opens_the_cleaning_plan_on_the_selected_rows(client, ready):
    ds = ready["id"]
    _, msg = send(client, ds, "clean these rows", **csv(selected_cells={"row_ids": [1, 2, 3], "columns": ["age"]}))
    p = msg["proposal"]
    assert p["kind"] == "clean_selection" and p["summary"] == "Clean with AI on the 3 selected rows"
    assert p["scope"]["kind"] == "selection" and p["impact"]["rows_affected"] == 3
    rejected = client.post(f"{API}/proposals/{p['id']}/reject")
    assert rejected.status_code == 204 and client.get(f"{API}/proposals/{p['id']}").json()["status"] == "rejected"
    _, msg = send(client, ds, "clean these rows", **csv(selected_cells={"row_ids": [1, 2, 3], "columns": ["age"]}))
    jobs_before = len(client.get(f"{API}/jobs", params={"dataset_id": ds}).json())
    plan = client.post(f"{API}/proposals/{msg['proposal']['id']}/approve", json={}).json()
    # PRD CLEAN-1: approving opens the plan with those rows as its scope; nothing runs until Start.
    assert plan["status"] == "draft" and plan["scope"]["kind"] == "selection" and plan["scope"]["rows"] == 3
    assert plan["scope"]["selection_id"] == msg["proposal"]["scope"]["selection_id"]
    assert len(client.get(f"{API}/jobs", params={"dataset_id": ds}).json()) == jobs_before
    assert client.get(f"{API}/datasets/{ds}").json()["clean_plan_id"] == plan["id"]
    assert client.get(f"{API}/proposals/{msg['proposal']['id']}").json()["status"] == "approved"
    job = client.post(f"{API}/datasets/{ds}/clean", json={"plan_id": plan["id"], "scope": plan["scope"] | {"rows": None}})
    assert job.status_code == 422  # the scope is CleanScope's shape: kind, selection_id, row_ids
    scope = {k: plan["scope"][k] for k in ("kind", "selection_id")}
    job = client.post(f"{API}/datasets/{ds}/clean", json={"plan_id": plan["id"], "scope": scope}).json()
    params = db_rows("SELECT params_json FROM jobs WHERE id = ?", job["id"])[0]["params_json"]
    assert '"kind": "selection"' in params


def test_an_unknown_row_is_refused_and_actions_stay_on_their_tab(client, ready):
    ds = ready["id"]
    _, msg = send(client, ds, "set the fare of row 999999 to 5", **csv())
    assert "proposal" not in msg and "isn't in this version" in msg["text"]
    _, msg = send(client, ds, "set the fare of row 1 to 100")  # dashboard: cells change from the CSV tab
    assert "proposal" not in msg and "CSV tab" in msg["text"]


def test_update_widget_changes_the_focused_widget_with_undo(client, ready):
    ds = ready["id"]
    w = client.post(f"{API}/datasets/{ds}/widgets", json={
        "op": {"type": "sql", "sql": "SELECT sex, AVG(fare) AS avg_fare FROM t WHERE {{rows}} GROUP BY 1 ORDER BY 1"},
        "view": {"type": "bar", "options": {"x": "sex", "y": "avg_fare"}}, "title": "Fare by sex"})
    assert w.status_code == 201, w.text
    wid = w.json()["widget"]["id"]
    _, msg = send(client, ds, "make it a pie chart", context={"tab": "dashboard", "focused_widget_id": wid})
    after = next(x for x in client.get(f"{API}/datasets/{ds}/widgets").json()["widgets"] if x["id"] == wid)
    assert after["spec"]["view"]["type"] == "pie" and after["title"] == "Average fare by sex"
    assert {"kind": "undo_widget", "widget_id": wid} in msg["actions"]
    assert any(b["type"] == "chart" and b["widget_id"] == wid for b in msg["blocks"])
    undone = client.post(f"{API}/widgets/{wid}/undo").json()
    assert undone["spec"]["view"]["type"] == "bar"


def test_a_two_part_question_runs_as_a_plan(client, ready):
    events, msg = send(client, ready["id"], "average fare by class, and what does pclass mean?")
    plan = next(d for e, d in events if e == "plan")["steps"]
    assert [s["text"] for s in plan] == ["Query the data: average fare by class", "Look at the column: what does pclass mean?"]
    steps = [(d["index"], d["status"]) for e, d in events if e == "plan.step"]
    assert steps == [(0, "running"), (0, "done"), (1, "running"), (1, "done")]
    assert msg["plan"]["steps"][1]["status"] == "done"
    assert any(b["type"] == "table" for b in msg["blocks"]) and "pclass" in msg["text"]


def test_export_a_notebook_from_chat_opens_the_dialog_with_options(client, ready):
    events, msg = send(client, ready["id"], "export a notebook without the data, with the canvas notes")
    assert not any(e == "status" and d["text"] == "Thinking…" and False for e, d in events)
    action = next(a for a in msg["actions"] if a["kind"] == "open_export")
    assert action["options"] == {"include_data": False, "include_notes": True}
    assert "without the data and with the canvas notes" in msg["text"]
    assert not db_rows("SELECT 1 FROM llm_calls WHERE purpose = 'route' AND dataset_id = ?", ready["id"])


def test_chat_changes_the_open_cleaning_plan_at_once(client, ready):
    # PRD CLEAN-8b: with a plan open, chat edits it straight away (nothing touches the data until Start)
    # and the reply is the code-written summary.
    ds = ready["id"]
    plan = client.post(f"{API}/datasets/{ds}/clean/plan").json()
    cabin = next(i for i in plan["items"] if i["key"] == "missing|cabin")
    assert plan["items"][0]["id"] == cabin["id"]  # f1 in the prompt: module order, most severe first

    events, msg = send(client, ds, "don't touch cabin", context={"tab": "dashboard", "plan_id": plan["id"]})
    assert msg["text"] == "Unticked 1 fix: missing values in cabin." and "proposal" not in msg
    after = client.get(f"{API}/clean-plans/{plan['id']}").json()
    assert not next(i for i in after["items"] if i["id"] == cabin["id"])["ticked"]
    _, msg = send(client, ds, "also trim spaces in name", **csv(plan_id=plan["id"]))
    assert msg["text"] == "Added 1 step on name."
    mine = client.get(f"{API}/clean-plans/{plan['id']}").json()["items"][0]
    assert (mine["module"], mine["source"], mine["column"], mine["instruction"]) == ("yours", "chat", "name", "Trim spaces in name")
    assert sum(1 for t, d in events_of(ds) if t == "plan.updated" and d["plan_id"] == plan["id"]) >= 3
    assert client.get(f"{API}/datasets/{ds}").json()["current_version"] == ready["current_version"]

    # A reply naming an item the plan doesn't have gets the one repair, then a plain answer.
    _, msg = send(client, ds, "leave the twelfth fix out", context={"tab": "dashboard", "plan_id": plan["id"]})
    assert msg["text"].startswith("I couldn't change the plan:") and "f99" in msg["text"]


def test_without_an_open_plan_chat_doesnt_edit_one(client, ready):
    ds = ready["id"]
    plan = client.post(f"{API}/datasets/{ds}/clean/plan").json()
    _, msg = send(client, ds, "don't touch cabin")  # no plan_id: edit_plan isn't one of the tab's tools
    assert "press Clean with AI to open one" in msg["text"]
    assert all(i["ticked"] for i in client.get(f"{API}/clean-plans/{plan['id']}").json()["items"] if i["change"])
    client.delete(f"{API}/clean-plans/{plan['id']}")
    _, msg = send(client, ds, "don't touch cabin", context={"tab": "dashboard", "plan_id": plan["id"]})
    assert "isn't open any more" in msg["text"]  # a discarded plan
