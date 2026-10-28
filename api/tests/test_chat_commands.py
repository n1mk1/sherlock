"""Cleaning commands typed in chat (docs/plans/chat-commands.md): the model writes pandas code, the sandbox dry-runs
it and the verifiers check it, the card shows the code and the effect, and OK saves it as one undoable step on the
version current then. Recorded model replies (`chat_commands.json`)."""

import shutil
from pathlib import Path

import pytest

from sherlock.agent import commands, loop
from sherlock.config import get_settings
from tests.test_chat import send
from tests.test_jobs import db_rows

API = "/api/v1"
LLM = Path(__file__).parent / "fixtures" / "llm"
pytestmark = pytest.mark.usefixtures("run_jobs")


@pytest.fixture(autouse=True)
def mocked(monkeypatch, tmp_path):
    folder = tmp_path / "llm"
    folder.mkdir()
    shutil.copy(LLM / "chat_commands.json", folder / "chat_commands.json")
    monkeypatch.setenv("LLM_MOCK", str(folder))
    get_settings.cache_clear()


@pytest.fixture
def ready(client):
    from tests.test_jobs import wait_status

    ds = client.post(f"{API}/datasets/sample").json()
    wait_status(client, ds["id"], "offer")
    client.post(f"{API}/datasets/{ds['id']}/use-as-is")
    wait_status(client, ds["id"], "ready")
    return client.get(f"{API}/datasets/{ds['id']}").json()


def cell(client, ds, row_id, column):
    rows = client.get(f"{API}/datasets/{ds}/rows", params={"offset": row_id - 1, "limit": 1}).json()["rows"]
    assert rows[0]["_row_id"] == row_id
    return rows[0]["cells"].get(column)


def version(client, ds):
    return client.get(f"{API}/datasets/{ds}").json()["current_version"]


def test_a_command_shows_its_code_and_effect_and_changes_nothing_until_ok(client, ready):
    ds, v = ready["id"], ready["current_version"]
    events, msg = send(client, ds, "make the sex column upper case")
    p = msg["proposal"]
    assert ("proposal", p) in [(e, d) for e, d in events if e == "proposal"]
    assert p["kind"] == "clean_step" and p["status"] == "pending" and p["base_version"] == v
    assert 'result["sex"].str.upper()' in p["code"] and p["columns"] == ["sex"]
    assert p["impact"] == {"cells_changed": 1309, "rows_affected": 1309, "quarantined": 0, "columns_added": []}
    assert p["summary"] == "Change 1,309 cells in 1,309 rows: sex"
    assert p["before_after"][0]["old"] in ("male", "female") and p["before_after"][0]["new"] in ("MALE", "FEMALE")
    assert "no rows lost" in p["checks"] and "no new blanks" in p["checks"]
    assert "press OK" in msg["text"]
    assert version(client, ds) == v and cell(client, ds, 1, "sex") == "female"  # nothing changed yet

    done = client.post(f"{API}/proposals/{p['id']}/approve", json={})
    assert done.status_code == 200, done.text
    assert done.json()["version"] == v + 1 and cell(client, ds, 1, "sex") == "FEMALE"
    step = done.json()["step"]
    assert step["created_by"] == "chat" and step["kind"] == "clean" and step["notebook_code"].endswith("df = result\n")
    assert client.get(f"{API}/proposals/{p['id']}").json()["status"] == "approved"
    again = client.post(f"{API}/proposals/{p['id']}/approve", json={})
    assert again.status_code == 409

    undone = client.post(f"{API}/datasets/{ds}/steps/{step['id']}/undo", json={"base_version": v + 1})
    assert undone.status_code == 200, undone.text
    assert cell(client, ds, 1, "sex") == "female"


def test_ok_after_the_data_changed_reruns_the_code_and_refreshes_when_the_effect_differs(client, ready):
    ds, v = ready["id"], ready["current_version"]
    _, msg = send(client, ds, "make the sex column upper case")
    p = msg["proposal"]
    # An edit elsewhere: same effect, so OK saves on the newer version.
    client.post(f"{API}/datasets/{ds}/edits", json={"base_version": v, "edits": [{"row_id": 2, "column": "fare", "value": "1"}]})
    done = client.post(f"{API}/proposals/{p['id']}/approve", json={}).json()
    assert done["version"] == v + 2 and cell(client, ds, 2, "fare") == 1 and cell(client, ds, 2, "sex") == "MALE"

    _, msg = send(client, ds, "make the sex column upper case")
    assert "proposal" not in msg and "nothing to change" in msg["text"]  # already upper case

    # An edit that the command would have changed: the effect differs, so the card refreshes for another OK.
    client.post(f"{API}/datasets/{ds}/steps/{done['step']['id']}/undo", json={"base_version": v + 2})
    v2 = version(client, ds)
    _, msg = send(client, ds, "make the sex column upper case")
    p = msg["proposal"]
    client.post(f"{API}/datasets/{ds}/edits", json={"base_version": v2, "edits": [{"row_id": 1, "column": "sex", "value": "FEMALE"}]})
    got = client.post(f"{API}/proposals/{p['id']}/approve", json={}).json()
    fresh = got["refreshed"]
    assert fresh["status"] == "pending" and fresh["rechecked_on"] == v2 + 1 and fresh["impact"]["cells_changed"] == 1308
    assert version(client, ds) == v2 + 1
    done = client.post(f"{API}/proposals/{p['id']}/approve", json={}).json()
    assert done["version"] == v2 + 2


def test_a_command_on_selected_rows_changes_only_those_rows_and_replays_with_its_scope(client, ready):
    ds, v = ready["id"], ready["current_version"]
    _, msg = send(client, ds, "make these upper case",
                  context={"tab": "csv", "selected_cells": {"row_ids": [1, 2, 3], "columns": ["sex"]}})
    p = msg["proposal"]
    assert p["kind"] == "clean_step" and p["scope"]["row_ids"] == [1, 2, 3]
    assert p["impact"]["cells_changed"] == 3 and p["summary"].endswith("on 3 selected rows")
    done = client.post(f"{API}/proposals/{p['id']}/approve", json={}).json()
    assert cell(client, ds, 3, "sex") == "FEMALE" and cell(client, ds, 4, "sex") == "male"
    assert "keep_outside_scope(df, result, rows=[1, 2, 3])" in done["step"]["notebook_code"]

    # Undo an earlier step: the command replays with its scope.
    first = db_rows("SELECT id FROM steps WHERE dataset_id = ? ORDER BY no LIMIT 1", ds)[0]["id"]
    client.post(f"{API}/datasets/{ds}/edits", json={"base_version": v + 1, "edits": [{"row_id": 9, "column": "fare", "value": "2"}]})
    edit = db_rows("SELECT id FROM steps WHERE dataset_id = ? AND kind = 'edit' ORDER BY no DESC LIMIT 1", ds)[0]["id"]
    assert first
    got = client.post(f"{API}/datasets/{ds}/steps/{edit}/undo", json={"base_version": v + 2})
    assert got.status_code == 200, got.text
    assert cell(client, ds, 3, "sex") == "FEMALE" and cell(client, ds, 4, "sex") == "male"


def test_delete_sets_rows_aside_after_a_repair_and_warns_when_it_is_many(client, ready):
    ds, v = ready["id"], ready["current_version"]
    _, msg = send(client, ds, "delete the passengers with no age")
    p = msg["proposal"]  # the first code dropped rows; the repair quarantines them
    assert p["impact"]["quarantined"] == 263 and p["impact"]["cells_changed"] == 0
    assert p["summary"] == "Set aside 263 rows (quarantined, not deleted)"
    assert "quarantine_rows" in p["code"]
    assert any("sets aside 263 of 1,309 rows" in w for w in p["warnings"])
    calls = db_rows("SELECT purpose, repaired FROM llm_calls WHERE dataset_id = ? AND purpose = 'step'", ds)
    assert [c["repaired"] for c in calls] == [0, 1]
    done = client.post(f"{API}/proposals/{p['id']}/approve", json={}).json()
    assert done["step"]["impact"]["rows_out"] == 1309 and done["step"]["impact"]["quarantined"] == 263
    page = client.get(f"{API}/datasets/{ds}/rows", params={"filter": '{"and": [{"col": "age", "op": "empty"}]}', "limit": 5}).json()
    assert page["total"] == 263 and all(r["quarantined"] for r in page["rows"])  # still in the file, set aside
    assert loop.DELETE_ASK.search("please remove the rows with no age")
    assert not loop.DELETE_ASK.search("remove the filter") and not loop.DELETE_ASK.search("remove the fare fix from the plan")
    assert version(client, ds) == v + 1


def test_a_computed_column_is_added_and_undone(client, ready):
    ds, v = ready["id"], ready["current_version"]
    _, msg = send(client, ds, "add family_size = sibsp + parch + 1")
    p = msg["proposal"]
    assert p["kind"] == "computed_column" and p["new_columns"] == ["family_size"]
    assert p["impact"]["columns_added"] == ["family_size"] and p["summary"].startswith("Add column family_size")
    done = client.post(f"{API}/proposals/{p['id']}/approve", json={}).json()
    assert done["step"]["kind"] == "computed_column" and cell(client, ds, 1, "family_size") == 1
    client.post(f"{API}/datasets/{ds}/steps/{done['step']['id']}/undo", json={"base_version": v + 1})
    rows = client.get(f"{API}/datasets/{ds}/rows", params={"limit": 1}).json()["rows"]
    assert "family_size" not in rows[0]["cells"]


def test_a_request_nothing_fits_or_unsafe_code_gets_the_reason_not_a_card(client, ready):
    ds, v = ready["id"], ready["current_version"]
    _, msg = send(client, ds, "repaint the unicorns in colour")
    assert "proposal" not in msg and msg["text"].startswith("I can't make that change to this file")
    _, msg = send(client, ds, "strip the titles from name")
    assert "proposal" not in msg and msg["text"] == commands.SAID["refused"]
    assert version(client, ds) == v


def test_a_change_then_a_question_defers_the_question_until_ok(client, ready):
    _, msg = send(client, ready["id"], "make sex upper case, then how many passengers are there by sex?")
    p = msg["proposal"]
    assert p["then"] == "how many passengers are there by sex?"
    assert "runs on the changed data once you press OK" in msg["text"]
    assert not [b for b in msg["blocks"] if b["type"] == "table"]


def test_ok_while_a_clean_runs_queues_the_command_until_it_ends(client, ready, app):
    ds, v = ready["id"], ready["current_version"]
    _, msg = send(client, ds, "make the sex column upper case")
    p = msg["proposal"]
    db_rows("UPDATE datasets SET status = 'cleaning' WHERE id = ?", ds)
    got = client.post(f"{API}/proposals/{p['id']}/approve", json={}).json()
    assert got["queued"]["status"] == "queued" and version(client, ds) == v
    db_rows("UPDATE datasets SET status = 'ready' WHERE id = ?", ds)
    from sherlock.db.connection import connect
    from sherlock.query.context import Env

    db = connect(app.state.settings)
    said = commands.run_queued(Env(app.state.settings, db, app.state.duckdb, app.state.bus), ds)
    assert said == [f"saved as v{v + 1}"] and version(client, ds) == v + 1
    assert client.get(f"{API}/proposals/{p['id']}").json()["status"] == "approved"


# --- questions SQL can't express: read-only pandas (`agent/analysis.py`) ---------------------------------


def test_a_question_for_code_is_answered_from_pandas_with_the_code_as_its_source(client, ready):
    ds, v = ready["id"], ready["current_version"]
    _, msg = send(client, ds, "what is the slope of fare against age?")
    table = next(b for b in msg["blocks"] if b["type"] == "table")
    assert [c["name"] for c in table["columns"]] == ["slope", "r_squared", "rows"]
    src = next(s for s in msg["sources"] if s.get("kind") == "code")
    assert "stats.linregress" in src["code"] and src["label"].startswith("Code (r1)")
    chip = next(r for b in msg["blocks"] if b["type"] == "text" for p in b["body"]["blocks"] for r in p["runs"]
                if r["type"] == "chip")
    assert float(chip["value"]) == pytest.approx(0.692, abs=0.01)  # from the executed code, never the model
    assert "proposal" not in msg and version(client, ds) == v  # read-only: nothing to OK, nothing saved


def test_a_query_sql_cannot_write_falls_back_to_pandas(client, ready):
    _, msg = send(client, ready["id"], "how many distinct surnames are there?")
    assert any(s.get("kind") == "code" for s in msg["sources"])
    number = next(b for b in msg["blocks"] if b["type"] == "number")
    assert 800 < number["value"] < 900


def test_analysis_code_that_reaches_the_system_is_refused(client, ready):
    _, msg = send(client, ready["id"], "load my files with os")
    assert not [b for b in msg["blocks"] if b["type"] in ("table", "number")]
    assert "couldn't work that out in code" in msg["text"] and "not allowed" in msg["text"]


def test_the_route_guards_send_commands_and_analysis_where_they_belong():
    # Live misses (Nemotron, 2026-10-27): imperative commands routed to a query or to analysis.
    for q in ("make fare a whole number by rounding", "fill the missing embarked values with S",
              "add family_size = sibsp + parch + 1", "please trim the spaces in name", "title-case the city column",
              "add a column total = units * price", "can you convert the dates to ISO format?"):
        assert loop.COMMAND.search(q), q
    for q in ("make a chart of fare by class", "average fare by class", "how do I fill missing values?",
              "show the rows with no age", "what is the slope of fare against age?"):
        assert not loop.COMMAND.search(q) or loop.HOW_TO.search(q), q
    assert loop.CODE_ASK.search("what is the slope of fare against age?")
    assert loop.CODE_ASK.search("cluster the customers by spend")
    assert not loop.CODE_ASK.search("average fare by class")
    assert loop.PLAN_WORDS.search("also trim spaces in name") and loop.PLAN_WORDS.search("leave cabin alone")
    assert not loop.PLAN_WORDS.search("trim the spaces in name")


def test_code_sent_with_escaped_line_breaks_is_read_as_lines():
    # Live: Nemotron sent "result = df.copy()\nresult[...] = ..." as one line, which the parser refused.
    escaped = "result = df.copy()" + chr(92) + "n" + 'result["a"] = 1'
    assert commands.plain(escaped) == 'result = df.copy()\nresult["a"] = 1'
    real = 'x = "a' + chr(92) + 'nb"\nresult = df'
    assert commands.plain(real) == real  # real line breaks: an escape inside a string stays
