"""Routing and honest limits from the live end-to-end test of 2026-10-26 (TRD §8.1's route guards, §8.2): rankings,
a count read as a value, a column swapped for another, misrouted questions, edit requests and forecasts. Recorded
model replies: `chat_titanic.json` plus `chat_routing.json`; each question is also in the ask eval, and its
expectation there is checked on the answer."""

import contextlib
import shutil
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from sherlock.agent import insight, loop
from sherlock.agent import prompts
from sherlock.agent.actions import out_of_range
from sherlock.agent.resolve import drop_counts
from sherlock.config import get_settings
from sherlock.eval import ask as ask_eval
from tests.test_answerers import driver_done
from tests.test_chat import blocks_of, send
from tests.test_chat_checks import kit
from tests.test_jobs import db_rows, wait_status

API = "/api/v1"
LLM = Path(__file__).parent / "fixtures" / "llm"
EVAL = {item["q"]: item["expect"] for items in ask_eval.load().values() for item in items}
pytestmark = pytest.mark.usefixtures("run_jobs")


@pytest.fixture(autouse=True)
def mocked(monkeypatch, tmp_path):
    folder = tmp_path / "llm"
    folder.mkdir()
    for name in ("chat_titanic.json", "chat_routing.json"):
        shutil.copy(LLM / name, folder / name)
    monkeypatch.setenv("LLM_MOCK", str(folder))
    get_settings.cache_clear()


@pytest.fixture
def ready(client):
    ds = client.post(f"{API}/datasets/sample").json()
    wait_status(client, ds["id"], "offer")
    client.post(f"{API}/datasets/{ds['id']}/use-as-is")
    wait_status(client, ds["id"], "ready")
    return ds


def purposes(ds_id: str) -> list[str]:
    return [c["purpose"] for c in db_rows("SELECT purpose FROM llm_calls WHERE dataset_id = ? AND message_id IS NOT NULL "
                                          "ORDER BY rowid", ds_id)]


def in_eval(msg: dict, question: str) -> None:
    ok, got = ask_eval.check(msg, EVAL[question])
    assert ok, f"{question}: {got}"


# --- 2 and 3: rankings, and a count isn't a value ------------------------------------------------

def test_a_ranking_routed_to_find_rows_is_a_query_with_order_and_limit(client, ready):
    q = "List the 5 passengers who paid the highest fare, with their names and fares"
    _, msg = send(client, ready["id"], q)
    table = blocks_of(msg, "table")[0]
    assert table["total"] == 5 and table["rows"][0][1] == pytest.approx(512.3292)
    assert "ORDER BY fare DESC" in msg["sources"][0]["sql"] and not table.get("selection_id")
    assert "predicate" not in purposes(ready["id"])  # find_rows never ran: its filter can't sort or stop at five
    in_eval(msg, q)


def test_a_number_that_counts_rows_is_never_a_filter_value(client, ready):
    q = "Who are the 10 youngest survivors?"
    _, msg = send(client, ready["id"], q)
    # The fixture's boat = '10' query answers only when the context names "10" as a value of boat.
    assert "boat" not in msg["sources"][0]["sql"]
    ages = [r[1] for r in blocks_of(msg, "table")[0]["rows"]]
    assert len(ages) == 10 and ages[1] == pytest.approx(0.4167)
    in_eval(msg, q)
    assert "is the LIMIT, never a value to filter on" in prompts.SQL and "is not a condition" in prompts.PREDICATE


def test_drop_counts_keeps_a_number_used_as_a_value():
    def names(question, texts):
        resolved = {"columns": {}, "values": {t: ["boat", t] for t in texts}, "widgets": {}, "unresolved": ["3"],
                    "unresolved_kinds": {"3": "value"}}
        drop_counts(resolved, question)
        return sorted(resolved["values"]), resolved["unresolved"]

    assert names("Who are the 10 youngest survivors?", ["10"]) == ([], ["3"])
    assert names("top 3 fares in boat 10", ["10"]) == (["10"], [])
    assert names("show the first 3 rows", []) == ([], [])
    assert names("survival rate in boat 10", ["10"]) == (["10"], ["3"])
    assert names("the 5 highest fares", ["5"]) == ([], ["3"])


# --- 4: a column isn't swapped for another without a word ---------------------------------------

def test_a_quantity_no_column_records_gets_the_honest_limit(client, ready):
    q = "What was the average income of first-class passengers?"
    _, msg = send(client, ready["id"], q)
    assert msg["text"].startswith("This file has no column that answers that.") and not blocks_of(msg, "number")
    assert "the average fare of first-class passengers" in msg["text"]
    assert purposes(ready["id"])[:3] == ["route", "sql", "sql_check"]
    in_eval(msg, q)


def test_a_column_that_records_the_word_is_kept_after_the_check(client, ready):
    # "port" isn't named like `embarked`, so the check asks; the repair keeps the query and the answer stands.
    _, msg = send(client, ready["id"], "Average fare by port")
    rows = {r[0]: r[1] for r in blocks_of(msg, "table")[0]["rows"]}
    assert rows["C"] == pytest.approx(62.3363, rel=1e-3) and "sql_check" in purposes(ready["id"])


def test_substituted_only_flags_a_word_named_nothing_like_its_column():
    k = kit({"fare": "DOUBLE", "pclass": "BIGINT", "sex": "VARCHAR", "survived": "BIGINT"},
            resolved={"unresolved": ["income", "women", "survivors"],
                      "unresolved_kinds": {"income": "column", "women": "column", "survivors": "column"}})
    assert len(k.substituted("income → fare, first-class → pclass = 1")) == 1
    assert k.substituted("women → sex = 'female'") == []  # a value read as a filter
    assert k.substituted("survivors → survived") == []    # named like the column
    assert k.substituted("class → pclass") == []          # not an unresolved word


# --- 11: misrouted questions -----------------------------------------------------------------------

def test_quarantine_questions_are_counted_in_code(client, ready):
    for q in ("Why were some rows quarantined?", "How many rows are quarantined and why?"):
        _, msg = send(client, ready["id"], q)
        assert "quarantined in this version" in msg["text"], msg["text"]
        assert not any(s["kind"] == "run" for s in msg["sources"]) and "no column" not in msg["text"]
        assert any(s["kind"] == "sql" and "_quarantine_reason IS NOT NULL" in s["sql"] for s in msg["sources"])
        in_eval(msg, q)


def test_quarantined_counts_the_rows_by_reason(monkeypatch):
    conn = duckdb.connect()
    conn.execute("CREATE TABLE t AS SELECT * FROM (VALUES (1, 'age not a number'), (2, NULL), (3, 'age not a number'), "
                 "(4, 'extra fields')) v(_row_id, _quarantine_reason)")
    monkeypatch.setattr(insight.ws, "connection", lambda *a: contextlib.nullcontext(conn))
    k = SimpleNamespace(env=None, dataset={"current_version": 2})
    reply = insight.quarantined(k, "r1")
    runs = reply.blocks[0]["body"]["blocks"][0]["runs"]
    assert runs[0]["type"] == "chip" and runs[0]["raw"] == 3
    assert reply.blocks[1]["rows"] == [["age not a number", 2], ["extra fields", 1]]
    conn.execute("UPDATE t SET _quarantine_reason = NULL")
    assert insight.quarantined(k, "r1").blocks[0]["body"]["blocks"][0]["runs"][0]["text"].startswith("No rows are quarantined")


def test_how_to_and_web_requests_go_where_they_belong(client, ready):
    q = "how do I undo a cleaning step?"
    _, msg = send(client, ready["id"], q)
    assert [s["kind"] for s in msg["sources"]] == ["help"] and "undo" in msg["text"].lower()
    in_eval(msg, q)
    q = "Search the web for what happened to passenger Allen, Miss. Elisabeth Walton after the voyage"
    _, msg = send(client, ready["id"], q)
    assert msg["text"] == "Web search isn't set up on this server, so I didn't look this up on the web."
    assert not any(s["kind"] == "step" for s in msg["sources"])
    in_eval(msg, q)


def test_why_a_group_differs_names_the_group(client, ready):
    driver_done(client, ready["id"])
    q = "Why did first class passengers survive more often?"
    _, msg = send(client, ready["id"], q)
    assert msg["text"].startswith("pclass ranks "), msg["text"]
    assert "The rate of survived by pclass is 1: 61.9%, 2: 43.0% and 3: 25.5%." in msg["text"]
    assert "not its cause" in msg["text"] and any(s["kind"] == "run" for s in msg["sources"])
    in_eval(msg, q)


# --- 12: edit requests -----------------------------------------------------------------------------

def test_delete_requests_say_chat_cant_delete_and_list_the_rows(client, ready):
    q = "delete all the male passengers"
    _, msg = send(client, ready["id"], q)
    assert msg["text"].startswith("I can't delete rows from chat") and "proposal" not in msg
    assert blocks_of(msg, "table")[0]["total"] == 843
    assert any(a["kind"] == "open_rows" for a in msg["actions"])
    in_eval(msg, q)
    assert loop.DELETE_ASK.search("please remove the rows with no age")
    assert not loop.DELETE_ASK.search("remove the filter") and not loop.DELETE_ASK.search("what did cleaning remove?")


def test_a_cell_edit_from_the_dashboard_is_a_proposal_with_a_range_check(client, ready):
    q = "set the age of row 5 to 200"
    _, msg = send(client, ready["id"], q)  # the Dashboard tab
    p = msg["proposal"]
    assert p["kind"] == "edit_cells" and p["edits"][0]["row_id"] == 5 and p["edits"][0]["value"] == "200"
    assert p["warnings"] == ["Check row 5 before you approve: 200 is outside the range age holds in this version "
                             "(0.167 to 80.00)."]
    assert p["warnings"][0] in msg["text"]
    in_eval(msg, q)


def test_out_of_range():
    edits = [{"row_id": 1, "column": "age", "value": "30"}, {"row_id": 2, "column": "age", "value": "-5"},
             {"row_id": 3, "column": "name", "value": "x"}, {"row_id": 4, "column": "age", "value": None}]
    assert out_of_range(edits, {"age": (0.17, 80.0)}) == [
        "Check row 2 before you approve: -5 is outside the range age holds in this version (0.17 to 80.00)."]


# --- 13: forecasts ---------------------------------------------------------------------------------

def test_a_forecast_question_says_what_it_would_need(client, ready):
    q = "What will the survival rate be next year?"
    _, msg = send(client, ready["id"], q)
    assert msg["text"].startswith("I can't forecast that: this file has no date or time column")
    assert purposes(ready["id"]) == []  # no model call, and no clarification
    in_eval(msg, q)
    assert loop.FORECAST.search("predict revenue for the coming quarter")
    assert loop.FORECAST.search("what will sales be in the next 3 months?")
    assert not loop.FORECAST.search("what will happen if I undo a step?")
    assert not loop.FORECAST.search("which passenger was next to the youngest?")
