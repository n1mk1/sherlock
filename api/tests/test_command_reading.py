"""The model's reading of a chat command (docs/plans/chat-commands-refinements.md R2): stored on the card, returned
by the API, kept when OK refreshes the card, checked before the dry run, and shown in the step's notebook text."""

import shutil
from pathlib import Path

import pytest

from sherlock.agent import commands
from sherlock.config import get_settings
from tests.test_chat import send
from tests.test_chat_commands import API, ready  # noqa: F401
from tests.test_jobs import db_rows

LLM = Path(__file__).parent / "fixtures" / "llm"
pytestmark = pytest.mark.usefixtures("run_jobs")
GOOD = "Upper-case every value in sex"


@pytest.fixture(autouse=True)
def mocked(monkeypatch, tmp_path):
    folder = tmp_path / "llm"
    folder.mkdir()
    shutil.copy(LLM / "command_reading.json", folder / "command_reading.json")
    monkeypatch.setenv("LLM_MOCK", str(folder))
    get_settings.cache_clear()


def test_the_reading_is_stored_on_the_card_and_returned_by_the_api(client, ready):  # noqa: F811
    _, msg = send(client, ready["id"], "upper case the sex column")
    p = msg["proposal"]
    assert p["reading"] == GOOD  # the first draft had a digit: this is the repaired one
    assert client.get(f"{API}/proposals/{p['id']}").json()["reading"] == GOOD
    assert p["summary"] == "Change 1,309 cells in 1,309 rows: sex"  # the counts stay code-written


@pytest.mark.parametrize("reading,asked,ok", [
    ("Round every fare to 2 decimal places", "round fare to 2 places", True),
    ("Replace double spaces with one space in home.dest", "replace double spaces in home.dest", True),
    ("Round every fare to 2 decimal places", "fare → 2dp", True),           # the user's "2dp" holds the 2
    ("Set aside the 263 rows with no age", "delete the rows with no age", False),  # a count the model made up
    ("Upper-case every value in sex", "upper case sex", True),
    ("Round every fare to two decimal places", "round fare to 2 places", True),  # "2" and "two" are one number
    ("Round every fare to 2 decimal places", "round fare to two places", True),
    ("Round every fare to three decimal places", "round fare to 2 places", False),
])
def test_the_reading_may_say_back_the_users_own_numbers(reading, asked, ok):
    assert (commands._reading_problem(reading, asked) is None) is ok


def test_a_reading_still_bad_after_the_repair_is_dropped_not_the_change(client, ready):  # noqa: F811
    _, msg = send(client, ready["id"], "yell the sex column")
    p = msg["proposal"]
    assert p["reading"] == "" and p["summary"] == "Change 1,309 cells in 1,309 rows: sex"  # the card shows the counts


def test_a_reading_with_because_is_repaired(client, ready):  # noqa: F811
    _, msg = send(client, ready["id"], "shout the sex column")
    assert msg["proposal"]["reading"] == GOOD


def test_the_reading_survives_a_refresh_and_shows_in_the_step_and_notebook(client, ready):  # noqa: F811
    ds, v = ready["id"], ready["current_version"]
    _, msg = send(client, ds, "upper case the sex column")
    p = msg["proposal"]
    client.post(f"{API}/datasets/{ds}/edits", json={"base_version": v, "edits": [{"row_id": 1, "column": "sex", "value": "FEMALE"}]})
    fresh = client.post(f"{API}/proposals/{p['id']}/approve", json={}).json()["refreshed"]
    assert fresh["reading"] == GOOD and fresh["impact"]["cells_changed"] == 1308
    done = client.post(f"{API}/proposals/{p['id']}/approve", json={}).json()
    assert done["step"]["decisions"][0]["chosen"] == GOOD
    assert db_rows("SELECT summary FROM steps WHERE id = ?", done["step"]["id"])[0]["summary"].startswith("Change ")

    from sherlock.notebook.cells import step as step_cells

    md, code = step_cells(done["step"])
    assert GOOD in md.source and "You asked: upper case the sex column" in md.source
    assert 'result["sex"].str.upper()' in code.source
