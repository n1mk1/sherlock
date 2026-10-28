"""Chat commands and the Cleaner's checks (docs/plans/chat-commands-refinements.md R3, R4): what the user asked for by
name outranks four checks (they become card warnings), the structural checks stay refusals, and every refusal says what
to do next in plain words. Recorded model replies (`command_checks.json`)."""

import re
import shutil
from pathlib import Path

import pytest

from sherlock.config import get_settings
from tests.test_chat import send
from tests.test_chat_commands import cell, ready, version  # noqa: F401 - `ready` is a fixture

API = "/api/v1"
LLM = Path(__file__).parent / "fixtures" / "llm"
pytestmark = pytest.mark.usefixtures("run_jobs")


@pytest.fixture(autouse=True)
def checks_mocked(monkeypatch, tmp_path):
    folder = tmp_path / "llm"
    folder.mkdir()
    shutil.copy(LLM / "command_checks.json", folder / "command_checks.json")
    monkeypatch.setenv("LLM_MOCK", str(folder))
    get_settings.cache_clear()


def number(text: str) -> int:
    return int(re.search(r"(\d[\d,]*)", text).group(1).replace(",", ""))


def warned_card(client, ds, ask, check_words):
    """The card for a command, with its one warning, and the check it must not tick."""
    _, msg = send(client, ds, ask)
    p = msg["proposal"]
    assert check_words not in p["checks"] and "no rows lost" in p["checks"]
    said = [r.get("text") for b in msg["blocks"] if b["type"] == "text" for para in b["body"]["blocks"] for r in para["runs"]]
    assert all(w in said for w in p["warnings"]) and p["warnings"]  # shown in chat too, as the quarantine warning is
    return p


def ok(client, p, v):
    done = client.post(f"{API}/proposals/{p['id']}/approve", json={})
    assert done.status_code == 200, done.text
    assert done.json()["version"] == v + 1
    return done.json()


def test_blanking_values_by_name_is_a_warning_not_a_refusal(client, ready):  # noqa: F811
    ds, v = ready["id"], ready["current_version"]
    p = warned_card(client, ds, "blank out the fares above 500", "no new blanks")
    [w] = p["warnings"]
    assert re.fullmatch(r"This empties \d+ cells that had values, in fare\.", w) and number(w) == p["impact"]["cells_changed"]
    assert version(client, ds) == v
    ok(client, p, v)
    assert cell(client, ds, 1, "fare") == pytest.approx(211.3375)
    assert client.get(f"{API}/datasets/{ds}").json()["current_version"] == v + 1


def test_filling_blanks_with_a_named_word_is_a_warning(client, ready):  # noqa: F811
    ds, v = ready["id"], ready["current_version"]
    p = warned_card(client, ds, "fill the missing cabin values with Unknown", "no placeholder fills")
    [w] = p["warnings"]
    assert re.fullmatch(r"This fills [\d,]+ blanks in cabin with the text 'Unknown'\. Sherlock can't tell that apart from a "
                        r"real value\.", w) and number(w) == p["impact"]["cells_changed"]
    ok(client, p, v)
    assert cell(client, ds, 1, "cabin") == "B5"


def test_making_two_values_the_same_is_a_warning(client, ready):  # noqa: F811
    ds, v = ready["id"], ready["current_version"]
    p = warned_card(client, ds, "make the embarked values Q and C the same", "no distinct values merged")
    assert p["warnings"] == ["This makes 2 different values in embarked the same value."]
    ok(client, p, v)


def test_turning_a_number_into_text_is_a_warning(client, ready):  # noqa: F811
    ds, v = ready["id"], ready["current_version"]
    p = warned_card(client, ds, "show fare as text with a dollar sign", "column types kept")
    assert p["warnings"] == ["fare becomes text: sorting and sums on it will stop working."]
    ok(client, p, v)
    assert cell(client, ds, 1, "fare") == "$211.34"
