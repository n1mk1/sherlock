"""Chat commands and the Cleaner's checks (docs/plans/chat-commands-refinements.md R3, R4): what the user asked for by
name outranks four checks (they become card warnings), the structural checks stay refusals, and every refusal says what
to do next in plain words. Recorded model replies (`command_checks.json`)."""

import json
import re
import shutil
from contextlib import closing
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from sherlock.agent import commands
from sherlock.cleaning import verifiers
from sherlock.config import get_settings
from sherlock.steps.diff import diff_versions
from tests.test_chat import send
from tests.test_chat_commands import cell, ready, version  # noqa: F401 - `ready` is a fixture
from tests.test_jobs import db_rows

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
    """The card for a command, with its warning shown in chat too, and the check it must not tick."""
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


# --- R4: the user's request outranks four checks -----------------------------------------------------------------


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


# --- R3: refusals leave no card, and say what to do next, in plain words -----------------------------------------

INTERNAL = re.compile(r"\w*(Error|Exception)\b|row_ledger|nan_introduced|placeholder_fill|merge_safety|parse_quarantine|"
                      r"pandera|dtype|traceback|\bsafe\b", re.I)


def refused(client, ds, ask):
    v = version(client, ds)
    _, msg = send(client, ds, ask)
    assert "proposal" not in msg and version(client, ds) == v
    assert not INTERNAL.search(msg["text"]), msg["text"]
    return msg["text"]


def test_rows_added_or_removed_are_refused_with_the_way_to_set_them_aside(client, ready):  # noqa: F811
    assert refused(client, ready["id"], "keep only the adults") == commands.REFUSED["row_ledger"]


def test_a_removed_column_is_refused(client, ready):  # noqa: F811
    assert refused(client, ready["id"], "get rid of the boat column") == \
        "The code would remove boat, and a command never removes a column."


def test_an_unexpected_new_column_is_refused(client, ready):  # noqa: F811
    assert refused(client, ready["id"], "mark the adults") == \
        "The code would add a column you didn't ask for (adult). To add one, say 'add a column …'."


def test_values_that_would_not_convert_and_are_not_set_aside_are_refused(client, ready):  # noqa: F811
    said = refused(client, ready["id"], "make ticket a number")
    assert said == commands.REFUSED["parse_quarantine"].format(n=number(said)) and number(said) > 100


def test_a_changed_row_number_is_refused_as_a_broken_structure(client, ready):  # noqa: F811
    assert refused(client, ready["id"], "number the rows from one") == commands.REFUSED["pandera"]


def test_an_empty_new_column_is_refused(client, ready):  # noqa: F811
    assert refused(client, ready["id"], "add a column flag") == commands.SAID["empty"].format(col="flag")


def test_a_change_that_changes_nothing_says_so(client, ready):  # noqa: F811
    assert refused(client, ready["id"], "make sex lower case") == \
        "Nothing in this version matches that, so there's nothing to change."


def test_mixed_types_stay_a_refusal_and_text_from_a_number_does_not():
    # A Parquet file can't hold mixed types, so no recorded command reaches this check: the frames stand in.
    before = pd.DataFrame({"_row_id": [1, 2], "_quarantine_reason": [None, None], "age": [30.0, 70.0]})
    mixed = before.assign(age=pd.Series([30.0, "old"], dtype=object))
    text = before.assign(age=pd.Series(["30.0", "70.0"], dtype=object))
    report = verifiers.verify(before, mixed, None, None, requested=True)
    assert report.hard["dtype"] != "pass" and commands._warned(report, before, mixed) == {}
    assert commands._refusal(report).user == commands.REFUSED["dtype"]
    report = verifiers.verify(before, text, None, None, requested=True)
    assert commands._warned(report, before, text)["dtype"] == ["age becomes text: sorting and sums on it will stop working."]


def test_a_column_the_file_lacks_names_the_closest_ones(client, ready):  # noqa: F811
    said = "This file has no column called Fare. The closest is fare."
    assert refused(client, ready["id"], "round the Fare column") == said
    # The model listed fare but its code used Fare: the run fails with a missing key, said the same way.
    assert refused(client, ready["id"], "round the cost of the ticket") == said
    assert commands.no_column("fare_us", ["fare_usd", "fare_uss", "name"]) == \
        "This file has no column called fare_us. The closest are fare_usd and fare_uss."
    assert commands.no_column("zzz", ["fare", "name"]) == "This file has no column called zzz."


def test_a_crash_says_the_code_did_not_run_and_never_the_exception(client, ready):  # noqa: F811
    assert refused(client, ready["id"], "convert fare to a whole number") == commands.SAID["crash"]


def test_a_repair_that_does_not_parse_does_not_repeat_the_first_drafts_reason(client, ready):  # noqa: F811
    # The first draft looks for Fare; the repair isn't a valid reply, so "no column called Fare" would be stale.
    assert refused(client, ready["id"], "halve the Fare values") == commands.SAID["default"]


def test_a_refusal_when_ok_is_pressed_uses_the_same_words(client, ready):  # noqa: F811
    ds, v = ready["id"], ready["current_version"]
    cards = [send(client, ds, "round fare to whole numbers")[1]["proposal"] for _ in range(2)]
    ok(client, cards[0], v)  # the second card's code now changes nothing
    got = client.post(f"{API}/proposals/{cards[1]['id']}/approve", json={})
    assert got.status_code == 409
    assert got.json()["error"]["message"] == (f"Couldn't run it on version {v + 1}. Nothing in this version matches that, "
                                              "so there's nothing to change. Nothing changed.")
    [(payload,)] = db_rows("SELECT payload_json FROM proposals WHERE id = ?", cards[1]["id"])
    assert json.loads(payload)["error"] == commands.SAID["nothing"]  # the card's "Couldn't run: …", never the model's text


# --- the rest of the message, as typed ---------------------------------------------------------------------------


def test_the_rest_of_a_message_is_kept_as_typed(client, ready):  # noqa: F811
    _, msg = send(client, ready["id"], "round fare to whole numbers then trim the names then count by sex")
    assert msg["proposal"]["then"] == "trim the names then count by sex"  # the user's words, not the planner's "count by sex?"


# --- a new type is an effect of its own ---------------------------------------------------------------------------


def test_a_command_that_only_changes_a_type_gets_a_card_and_ok_saves_it(client, ready):  # noqa: F811
    ds, v = ready["id"], ready["current_version"]
    _, msg = send(client, ds, "make age a whole number")  # on the raw ages, some values change too: 28.5 → 28
    p = msg["proposal"]
    assert p["impact"]["columns_retyped"] == {"age": "whole numbers"} and p["impact"]["cells_changed"] > 0
    assert p["summary"].startswith("Make age whole numbers · Change ")
    assert all(float(c["old"]) % 1 for c in p["before_after"])  # only the ages with a fraction count as changed
    assert client.post(f"{API}/proposals/{p['id']}/reject").status_code == 204

    ok(client, send(client, ds, "round age to whole years")[1]["proposal"], v)
    _, msg = send(client, ds, "make age a whole number")  # now 22.0 → 22: no value changes, only the type
    p = msg["proposal"]
    assert p["impact"]["cells_changed"] == 0 and p["summary"] == "Make age whole numbers" and "kept" not in p
    step = ok(client, p, v + 1)["step"]
    assert step["summary"] == "Make age whole numbers"
    [d] = step["decisions"]
    assert (d["question"], d["chosen"], d["reason"]) == ("What does it do?", "Store every age as a whole number",
                                                         "You pressed OK in chat")
    [(cols,)] = db_rows("SELECT columns_json FROM versions WHERE dataset_id = ? AND version = ?", ds, v + 2)
    assert {c["name"]: c["type"] for c in json.loads(cols)}["age"] == "BIGINT"


def test_a_number_to_number_type_change_compares_the_numbers(tmp_path):
    old, new = tmp_path / "o.parquet", tmp_path / "n.parquet"
    with closing(duckdb.connect()) as conn:
        conn.execute("CREATE TABLE t AS SELECT * FROM (VALUES (1::BIGINT, NULL::VARCHAR, 22.0::DOUBLE), "
                     "(2, NULL, 28.5)) v(_row_id, _quarantine_reason, age)")
        conn.execute(f"COPY t TO '{old.as_posix()}' (FORMAT PARQUET)")
        conn.execute(f"COPY (SELECT _row_id, _quarantine_reason, [22, 28][_row_id]::BIGINT AS age FROM t) "
                     f"TO '{new.as_posix()}' (FORMAT PARQUET)")
    d = diff_versions(old, new)  # cast to the new type, 28.5 would round to 28 and hide the change
    assert d.retyped == {"age": ("DOUBLE", "BIGINT")} and [r[:4] for r in d.lineage] == [(2, "age", "28.5", "28")]
    assert commands.holds("DECIMAL(3,1)") == "numbers" and commands.holds("BIGINT") == "whole numbers"
