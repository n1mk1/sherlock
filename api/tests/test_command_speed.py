"""Faster chat commands (docs/plans/chat-commands-refinements.md R5): OK commits the card's kept dry run when the
version hasn't moved (no second sandbox run), the kept file goes away with the card, each stage is said, and the
prompt carries example values for the columns the message names. Recorded model replies (`command_speed.json`)."""

import shutil
from pathlib import Path

import pytest

from sherlock.agent import commands
from sherlock.config import get_settings
from sherlock.db.connection import connect
from sherlock.sandbox import runner
from tests.test_chat import send
from tests.test_chat_commands import cell, ready, version  # noqa: F401
from tests.test_jobs import db_rows

API = "/api/v1"
LLM = Path(__file__).parent / "fixtures" / "llm"
pytestmark = pytest.mark.usefixtures("run_jobs")


@pytest.fixture(autouse=True)
def mocked(monkeypatch, tmp_path):
    folder = tmp_path / "llm"
    folder.mkdir()
    shutil.copy(LLM / "command_speed.json", folder / "command_speed.json")
    monkeypatch.setenv("LLM_MOCK", str(folder))
    get_settings.cache_clear()


@pytest.fixture
def sandbox_calls(monkeypatch):
    calls = []
    real = runner.execute

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(runner, "execute", counting)
    return calls


def kept_files():
    return sorted(get_settings().data_dir.glob("users/*/datasets/*/.chat_*"))


def statuses(events):
    return [d["text"] for e, d in events if e == "status"]


def test_ok_on_an_unchanged_version_makes_no_second_sandbox_run(client, ready, sandbox_calls):
    ds, v = ready["id"], ready["current_version"]
    _, msg = send(client, ds, "shout every value in sex")
    p = msg["proposal"]
    assert len(sandbox_calls) == 1
    assert [f.name for f in kept_files()] == [f".chat_{p['id']}.parquet"]
    done = client.post(f"{API}/proposals/{p['id']}/approve", json={})
    assert done.status_code == 200, done.text
    assert len(sandbox_calls) == 1  # OK ran no code
    assert done.json()["version"] == v + 1 and cell(client, ds, 1, "sex") == "FEMALE"
    step = done.json()["step"]
    assert step["summary"] == p["summary"] and step["verifiers"]["row_ledger"] == "pass"
    assert kept_files() == []
    undone = client.post(f"{API}/datasets/{ds}/steps/{step['id']}/undo", json={"base_version": v + 1})
    assert undone.status_code == 200 and cell(client, ds, 1, "sex") == "female"


def test_ok_after_another_step_runs_the_code_again_and_drops_the_stale_file(client, ready, sandbox_calls):
    ds, v = ready["id"], ready["current_version"]
    _, msg = send(client, ds, "shout every value in sex")
    p = msg["proposal"]
    client.post(f"{API}/datasets/{ds}/edits", json={"base_version": v, "edits": [{"row_id": 2, "column": "fare", "value": "1"}]})
    done = client.post(f"{API}/proposals/{p['id']}/approve", json={}).json()
    assert len(sandbox_calls) == 2  # the dry run, then the run on the newer version
    assert done["version"] == v + 2 and cell(client, ds, 2, "fare") == 1 and cell(client, ds, 2, "sex") == "MALE"
    assert kept_files() == []

    # An edit the command would have changed: the effect differs, so the card refreshes and keeps its new run,
    # which the next OK saves with no third sandbox run.
    client.post(f"{API}/datasets/{ds}/steps/{done['step']['id']}/undo", json={"base_version": v + 2})
    v2 = version(client, ds)
    _, msg = send(client, ds, "shout every value in sex")
    p = msg["proposal"]
    client.post(f"{API}/datasets/{ds}/edits", json={"base_version": v2, "edits": [{"row_id": 1, "column": "sex", "value": "FEMALE"}]})
    got = client.post(f"{API}/proposals/{p['id']}/approve", json={}).json()
    assert got["refreshed"]["impact"]["cells_changed"] == 1308 and [f.name for f in kept_files()] == [f".chat_{p['id']}.parquet"]
    runs = len(sandbox_calls)
    done = client.post(f"{API}/proposals/{p['id']}/approve", json={}).json()
    assert done["version"] == v2 + 2 and len(sandbox_calls) == runs and kept_files() == []


def test_cancel_removes_the_kept_file(client, ready):
    _, msg = send(client, ready["id"], "shout every value in sex")
    assert len(kept_files()) == 1
    assert client.post(f"{API}/proposals/{msg['proposal']['id']}/reject").status_code == 204
    assert kept_files() == []


def test_a_repaired_draft_keeps_one_file_and_says_it_is_fixing_the_code(client, ready, sandbox_calls):
    events, msg = send(client, ready["id"], "set aside the passengers with a blank age")
    texts = statuses(events)
    assert len(kept_files()) == 1 and msg["proposal"]["impact"]["quarantined"] == 263
    assert len(sandbox_calls) == 2
    assert texts.count("Writing the code") == 1 and texts.count("Running it on a copy of the file") == 2
    assert texts.index("Fixing the code") > texts.index("Running it on a copy of the file")


def test_each_stage_is_said_in_order(client, ready):
    events, _ = send(client, ready["id"], "shout every value in sex")
    texts = statuses(events)
    assert texts.index("Writing the code") < texts.index("Running it on a copy of the file")
    assert "Fixing the code" not in texts


def test_the_startup_sweep_removes_files_of_cards_that_are_not_waiting(client, ready):
    _, msg = send(client, ready["id"], "shout every value in sex")
    pid = msg["proposal"]["id"]
    stray = kept_files()[0].parent / f".chat_{'ab' * 16}.parquet"  # a dry run cut off before it became a card
    stray.write_bytes(b"x")
    conn = connect(get_settings())
    try:
        assert commands.sweep(get_settings(), conn) == 1 and [f.name for f in kept_files()] == [f".chat_{pid}.parquet"]
        conn.execute("UPDATE proposals SET status = 'rejected' WHERE id = ?", (pid,))
        assert commands.sweep(get_settings(), conn) == 1 and kept_files() == []
        assert commands.sweep(get_settings(), conn) == 0
    finally:
        conn.close()
    assert db_rows("SELECT status FROM proposals WHERE id = ?", pid)[0]["status"] == "rejected"


def test_the_prompt_gets_example_values_only_for_the_columns_the_message_names(client, ready, monkeypatch):
    seen = []
    real = commands.examples
    monkeypatch.setattr(commands, "examples", lambda *a: seen.append(real(*a)) or seen[-1])
    send(client, ready["id"], "shout every value in sex")
    lines = seen[0].splitlines()
    assert any(ln.startswith("- sex: VARCHAR (e.g. ") for ln in lines)
    assert any(ln.startswith("- fare: ") for ln in lines) and not any(ln.startswith("- fare: ") and "e.g." in ln for ln in lines)
    assert len(lines) > 5  # every column still has its type
