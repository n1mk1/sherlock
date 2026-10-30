"""Chat does to the file what the grid and a spreadsheet do: delete rows and columns, rename and move columns, add a
blank column, add rows with values, set rows aside and bring them back, and sort the grid. Each change is a card the
user reads before OK, and Undo takes it back. Recorded model replies (`chat_excel.json`)."""

import shutil
from pathlib import Path

import pytest

from sherlock.agent import commands, loop
from sherlock.config import get_settings
from tests.test_chat import send
from tests.test_chat_commands import version

API = "/api/v1"
LLM = Path(__file__).parent / "fixtures" / "llm"
pytestmark = pytest.mark.usefixtures("run_jobs")


@pytest.fixture(autouse=True)
def mocked(monkeypatch, tmp_path):
    folder = tmp_path / "llm"
    folder.mkdir()
    shutil.copy(LLM / "chat_excel.json", folder / "chat_excel.json")
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


def page(client, ds, **params):
    got = client.get(f"{API}/datasets/{ds}/rows", params={"limit": 5, **params}).json()
    return {**got, "columns": [c["name"] for c in got["columns"]]}


def ok(client, p):
    done = client.post(f"{API}/proposals/{p['id']}/approve", json={})
    assert done.status_code == 200, done.text
    return done.json()


def undo(client, ds, step_id, base):
    got = client.post(f"{API}/datasets/{ds}/steps/{step_id}/undo", json={"base_version": base, "confirm": True})
    assert got.status_code == 200, got.text


def test_set_aside_rows_and_bring_them_back(client, ready):
    ds, v = ready["id"], ready["current_version"]
    _, msg = send(client, ds, "set aside the passengers with no age")
    p = msg["proposal"]
    assert p["summary"] == "Set aside 263 rows (quarantined, not deleted)"
    ok(client, p)
    _, msg = send(client, ds, "bring back the set-aside rows")
    p = msg["proposal"]
    assert p["impact"]["rows_restored"] == 263 and p["summary"] == "Bring back 263 set-aside rows"
    ok(client, p)
    assert version(client, ds) == v + 2
    assert not any(r["quarantined"] for r in page(client, ds, filter='{"and": [{"col": "age", "op": "empty"}]}')["rows"])


def test_delete_a_column_and_undo_it(client, ready):
    ds, v = ready["id"], ready["current_version"]
    _, msg = send(client, ds, "delete the column body")
    p = msg["proposal"]
    assert p["impact"]["columns_removed"] == ["body"] and p["summary"] == "Delete column body"
    assert "body" in page(client, ds)["columns"]  # nothing changed before OK
    done = ok(client, p)
    assert "body" not in page(client, ds)["columns"]
    undo(client, ds, done["step"]["id"], v + 1)
    assert "body" in page(client, ds)["columns"]


def test_code_that_deletes_a_column_nobody_asked_for_is_refused(client, ready):
    ds, v = ready["id"], ready["current_version"]
    _, msg = send(client, ds, "delete the column boat")
    assert "proposal" not in msg and msg["text"] == commands.SAID["removed"].format(cols="cabin")
    assert version(client, ds) == v


def test_rename_and_move_columns(client, ready):
    ds = ready["id"]
    _, msg = send(client, ds, "rename home.dest to destination")
    p = msg["proposal"]
    assert p["impact"]["columns_renamed"] == {"home.dest": "destination"} and p["impact"]["columns_added"] == []
    assert p["summary"] == "Rename home.dest to destination"
    ok(client, p)
    cols = page(client, ds)["columns"]
    assert "destination" in cols and "home.dest" not in cols
    _, msg = send(client, ds, "move fare to the front")
    p = msg["proposal"]
    assert p["impact"].get("columns_moved") and p["summary"] == "Reorder the columns"
    ok(client, p)
    assert [c for c in page(client, ds)["columns"] if not c.startswith("_")][0] == "fare"


def test_a_blank_column_is_added_with_a_note_on_the_card(client, ready):
    ds = ready["id"]
    _, msg = send(client, ds, "add a column notes")
    p = msg["proposal"]
    assert p["impact"]["columns_added"] == ["notes"] and "notes is empty in every row." in p["warnings"]
    ok(client, p)
    assert page(client, ds)["rows"][0]["cells"]["notes"] is None


def test_delete_a_numbered_row_for_real_and_undo_brings_it_back(client, ready):
    ds, v = ready["id"], ready["current_version"]
    _, msg = send(client, ds, "delete row 5")
    p = msg["proposal"]
    assert p["kind"] == "clean_step" and p["impact"]["rows_deleted"] == 1 and p["summary"] == "Delete 1 row"
    assert "no rows lost" not in p["checks"]
    done = ok(client, p)
    assert done["step"]["impact"]["rows_out"] == 1308 and page(client, ds)["total"] == 1308
    undo(client, ds, done["step"]["id"], v + 1)
    assert page(client, ds)["total"] == 1309


def test_undoing_an_earlier_step_replays_a_delete_after_it(client, ready):
    ds, v = ready["id"], ready["current_version"]
    _, msg = send(client, ds, "delete the column body")
    first = ok(client, msg["proposal"])
    _, msg = send(client, ds, "delete row 5")
    ok(client, msg["proposal"])
    undo(client, ds, first["step"]["id"], v + 2)  # replays the row delete on the version with body
    got = page(client, ds)
    assert "body" in got["columns"] and got["total"] == 1308


def test_delete_the_selected_rows_keeps_the_others(client, ready):
    ds = ready["id"]
    _, msg = send(client, ds, "delete these rows", context={"tab": "csv", "selected_cells": {"row_ids": [1, 2, 3], "columns": ["age"]}})
    p = msg["proposal"]
    assert p["impact"]["rows_deleted"] == 3 and p["summary"] == "Delete 3 rows · on 3 selected rows"
    ok(client, p)
    got = page(client, ds)
    assert got["total"] == 1306 and got["rows"][0]["_row_id"] == 4


def test_add_a_row_with_values(client, ready):
    ds, v = ready["id"], ready["current_version"]
    _, msg = send(client, ds, "add a row with name Jane Doe, sex female and age 30", context={"tab": "csv"})
    p = msg["proposal"]
    assert p["kind"] == "edit_cells" and p["new_rows"] == [{"name": "Jane Doe", "sex": "female", "age": "30"}]
    assert p["summary"] == "Add 1 row at the end" and p["impact"]["rows_added"] == 1
    ok(client, p)
    assert version(client, ds) == v + 1
    last = page(client, ds, offset=1309)["rows"]
    assert last[0]["cells"]["name"] == "Jane Doe" and last[0]["cells"]["age"] == 30


def test_sort_by_a_column_sorts_the_grid_without_a_model_call(client, ready):
    ds = ready["id"]
    _, msg = send(client, ds, "sort by fare descending")
    assert msg["actions"] == [{"kind": "sort_grid", "column": "fare", "dir": "desc"}]
    assert msg["text"].startswith("The grid is sorted by fare, largest first")
    _, msg = send(client, ds, "clear the sort")
    assert msg["actions"] == [{"kind": "sort_grid", "column": None, "dir": "asc"}]


def test_the_guards_send_each_spreadsheet_request_where_it_belongs():
    cols = ["fare", "home.dest", "Age"]
    assert loop.sort_of("sort by fare", cols) == {"column": "fare", "dir": "asc"}
    assert loop.sort_of("Sort the rows by age, highest first", cols) == {"column": "Age", "dir": "desc"}
    assert loop.sort_of("order by home dest z to a", cols) == {"column": "home.dest", "dir": "desc"}
    assert loop.sort_of("order the classes by average fare", cols) is None  # not a column: a question
    assert loop.DELETE_ASK.search("delete the column cabin") and loop.DELETE_ASK.search("remove the duplicates")
    assert not loop.DELETE_ASK.search("remove the sort")
    assert loop.ADD_ROW.search("add a row with name Bob") and loop.ADD_ROW.search("insert 3 blank rows")
    assert not loop.ADD_ROW.search("add a column total")
    assert loop.ROW_OP.search("restore row 12") and loop.ROW_OP.search("delete row 5")
    assert not loop.ROW_OP.search("set the fare of row 9 to 30")
