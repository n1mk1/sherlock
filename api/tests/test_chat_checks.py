"""Chat checks (plan 2.7–2.9; TRD §8.1 steps 3 and 5, PRD ASK-6, STORY-3, STORY-8): every `ask_data` result
checked in code with one repair, clarifications with buttons for names nothing resolved, and one wording
check for the chat's model-written text. Recorded model replies: `chat_titanic.json` plus `chat_checks.json`."""

import shutil
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from sherlock.agent import compose as comp
from sherlock.agent.answerers import Result, Scope, Toolkit, reading_text, widget_title
from sherlock.agent.insight import pair_options
from sherlock.agent.loop import checked_clarification
from sherlock.agent.resolve import candidates
from sherlock.config import get_settings
from sherlock.llm.client import StructuredOutputError
from sherlock.llm.schemas import Route
from sherlock.stories.wording import title_problem, wording_problem
from tests.test_answerers import driver_done
from tests.test_chat import blocks_of, send
from tests.test_jobs import db_rows, wait_status

API = "/api/v1"
LLM = Path(__file__).parent / "fixtures" / "llm"
pytestmark = pytest.mark.usefixtures("run_jobs")


@pytest.fixture(autouse=True)
def mocked(monkeypatch, tmp_path):
    folder = tmp_path / "llm"
    folder.mkdir()
    for name in ("chat_titanic.json", "chat_checks.json"):
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


# --- 2.7: the result checked in code, then one repair -------------------------------------------

def test_a_wrong_case_literal_is_repaired_with_what_code_found(client, ready):
    _, msg = send(client, ready["id"], "survival rate of Female passengers")
    # The first query compared sex with 'Female': no row matched and the rate was null. The repair saw both
    # findings (the fixture only answers when its prompt quotes them) and its query replaced the first.
    number = blocks_of(msg, "number")[0]
    assert number["value"] == pytest.approx(0.7275, abs=1e-3)
    assert "sex = 'female'" in msg["sources"][0]["sql"]
    calls = db_rows("SELECT purpose FROM llm_calls WHERE dataset_id = ? AND message_id IS NOT NULL ORDER BY rowid", ready["id"])
    assert [c["purpose"] for c in calls][:3] == ["route", "sql", "sql_check"]


def kit(types: dict, resolved: dict | None = None, values: dict | None = None, roles: dict | None = None) -> Toolkit:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE value_index (dataset_id TEXT, column TEXT, value TEXT, count INTEGER)")
    for col, vals in (values or {}).items():
        db.executemany("INSERT INTO value_index VALUES ('d', ?, ?, ?)", [(col, v, 100 - i) for i, v in enumerate(vals)])
    resolved = {"columns": {}, "values": {}, "widgets": {}, "unresolved": [], "unresolved_kinds": {}, **(resolved or {})}
    return Toolkit(SimpleNamespace(db=db), None, None, {"id": "d"}, "", Scope(), resolved=resolved, types=types,
                   roles=roles or {c: "dimension" for c in types}, example="the average fare by pclass")


def result(columns: list[tuple[str, str]], rows: list[list]) -> Result:
    return Result("r1", "sql", "tpl", [{"name": n, "type": t} for n, t in columns], rows, len(rows))


def test_the_findings_code_checks():
    types = {"sex": "VARCHAR", "fare": "DOUBLE", "pclass": "BIGINT", "age": "DOUBLE", "ticket": "VARCHAR"}
    roles = {"sex": "dimension", "fare": "measure", "pclass": "dimension", "age": "measure", "ticket": "id"}
    k = kit(types, {"columns": {"class": "pclass", "age": "age", "tickets": "ticket"}, "values": {"women": ["sex", "female"]}},
            {"sex": ["male", "female"]}, roles)
    sql = "SELECT pclass, AVG(fare) AS avg_fare FROM t WHERE {{rows}} AND sex = 'Female' GROUP BY 1"
    found = k.findings(result([("pclass", "BIGINT"), ("avg_fare", "DOUBLE")], []), sql)
    # `ticket` is an ID column named like the records ("how many tickets"): the rows themselves, not a column to use.
    assert found == ["The query returned no rows.",
                     "The question names age (“age”), but the query never uses that column.",
                     "sex = 'Female' matches no row: sex has 'male', 'female'."]
    # A null measure in every row; `IN` lists are read too; a column without a value index isn't judged.
    sql = "SELECT AVG(age) AS a FROM t WHERE {{rows}} AND sex IN ('female', 'Male') AND pclass = 1 AND ticket = 'X'"
    found = k.findings(result([("a", "DOUBLE")], [[None]]), sql)
    assert found == ["The result column a is empty (null) in every row.",
                     "sex = 'Male' matches no row: sex has 'male', 'female'."]
    # A clean result has nothing to say; `lower(sex)` and `SELECT *` are left alone.
    sql = "SELECT * FROM t WHERE {{rows}} AND lower(sex) = 'female'"
    assert k.findings(result([("pclass", "BIGINT")], [[1]]), sql) == []


# --- 2.8: clarifications with buttons --------------------------------------------------------------

def test_an_unresolved_name_becomes_a_clarification_and_the_choice_resumes(client, ready):
    _, ask = send(client, ready["id"], "average fair by class")
    clar = ask["clarification"]
    assert clar["question"] == "Which column do you mean by “fair”?" and clar["options"][0] == "fare"
    assert 2 <= len(clar["options"]) <= 3 and ask["blocks"] == []
    _, msg = send(client, ready["id"], "fare", clarification_of=ask["id"], choice="fare")
    # The fixture's SQL step only answers when its context says "“fair” is column fare".
    table = blocks_of(msg, "table")[0]
    assert [c["name"] for c in table["columns"]] == ["pclass", "avg_fare"] and table["total"] == 3


def test_which_column_has_buttons_too(client, ready):
    _, ask = send(client, ready["id"], "what does the sibs column mean?")
    assert ask["clarification"]["question"] == "Which column do you mean?"
    assert ask["clarification"]["options"][0] == "sibsp" and len(ask["clarification"]["options"]) == 3
    _, msg = send(client, ready["id"], "sibsp", clarification_of=ask["id"], choice="sibsp")
    first = msg["blocks"][0]["body"]["blocks"][0]["runs"][0]
    assert first == {"type": "label", "ref": "column:sibsp", "text": "sibsp"}
    # A follow-up after the clarification still sees the thread's earlier answer, not an empty focus.
    thread = client.get(f"{API}/datasets/{ready['id']}/chat").json()
    assert [m.get("clarification") is not None for m in thread if m["role"] == "assistant"] == [True, False]


def test_candidates_only_for_a_name_that_looks_like_the_files():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE value_index (dataset_id TEXT, column TEXT, value TEXT, count INTEGER)")
    db.executemany("INSERT INTO value_index VALUES ('d', 'sex', ?, ?)", [("male", 843), ("female", 466)])
    cols = ["pclass", "survived", "name", "sex", "age", "sibsp", "parch", "ticket", "fare", "cabin", "embarked"]
    options = candidates(db, "d", "fair", "column", cols)
    assert options[0] == ("fare", {"column": "fare"}) and len(options) == 2
    assert candidates(db, "d", "nationality", "column", cols) == []  # nothing close: the honest "no column" stands
    assert candidates(db, "d", "femail", "value", cols)[0] == ("female", {"value": ["sex", "female"]})


def test_pair_options_for_a_test():
    card = {"target_candidates": ["survived"], "columns": [
        {"name": "survived", "type": "int", "distinct": 2}, {"name": "sex", "type": "category", "distinct": 2},
        {"name": "fare", "type": "float", "distinct": 280}, {"name": "name", "type": "text", "distinct": 1307},
        {"name": "embarked", "type": "category", "distinct": 3}]}
    options = pair_options("is the fare different?", card, ["fare"])
    assert sorted(o for o, _ in options) == ["fare and embarked", "fare and sex", "fare and survived"]  # never name (text)
    assert dict(options)["fare and sex"] == {"columns": ["fare", "sex"]}
    assert pair_options("anything?", card, [])[0][0].startswith("survived and ")


# --- 2.9: one wording check ------------------------------------------------------------------------

def test_the_wording_check():
    assert "'Two'" in wording_problem("Two hundred passengers paid more")
    assert "because" in wording_problem("Fares are higher because of class")
    assert wording_problem("value:sex:female is higher") and wording_problem("see [the table]")
    assert wording_problem("First class paid the most on average") is None
    assert title_problem("Top 10 fares") and title_problem("Fares rise because of class") and title_problem(" ")
    assert title_problem("Average fare by port") is None


def test_a_widget_title_that_fails_falls_back_to_the_templated_one():
    spec = {"scope": {"columns": {"x": "embarked", "y": "avg_fare"}}, "view": {"type": "bar"}}
    assert widget_title("Average fare by port", spec) == "Average fare by port"
    assert widget_title("Top 10 fares by port", spec) == "Average avg_fare by embarked"
    assert widget_title("How the port drives fares", spec) == "Average avg_fare by embarked"


def test_reading_and_closest():
    assert reading_text(" class → pclass ") == "class → pclass"
    assert reading_text("class → pclass, because it drives fare") == ""
    k = kit({"fare": "DOUBLE"})
    assert k._closest("passengers by home destination").endswith("“passengers by home destination”")
    assert k._closest("the two classes by fare").endswith("“the average fare by pclass”")  # the file's own example


def test_router_clarification_options_are_checked():
    def route(question, options):
        return Route(intents=["ask_data"], ambiguous=True, multi_step=False, entities=[],
                     clarification={"question": question, "options": options})

    assert checked_clarification(route("Which groups?", ["men and women", "the passenger classes"])) == \
        {"question": "Which groups?", "options": ["men and women", "the passenger classes"]}
    assert checked_clarification(route("Which groups?", ["men and women", "the three classes", "the ports"])) == \
        {"question": "Which groups?", "options": ["men and women", "the ports"]}
    assert checked_clarification(route("Which groups?", ["men and women", "the three classes"])) is None
    assert checked_clarification(route("Which of the two?", ["men", "women"])) is None


def test_a_model_card_answer_keeps_its_tables_when_compose_falls_back(client, ready):
    driver_done(client, ready["id"])
    _, msg = send(client, ready["id"], "how well does the model do?")  # the recorded prose has digits, twice
    tables = blocks_of(msg, "table")
    assert tables and all(t["rows"] for t in tables) and msg["text"].startswith("Here is the result")
    assert any(s["kind"] == "run" for s in msg["sources"])


def test_a_clarification_that_fails_the_check_is_answered_instead(client, ready):
    _, msg = send(client, ready["id"], "which deck had the most passengers?")
    assert "clarification" not in msg and blocks_of(msg, "table")


class OneReply:
    """A model that always gives one reply; the validator's error is a failed call, as after a repair."""

    def __init__(self, reply: dict) -> None:
        self.reply = reply

    def structured(self, role, messages, schema, *, purpose, scope, validate=None):
        value = schema.model_validate(self.reply)
        if validate:
            try:
                validate(value)
            except ValueError as exc:
                raise StructuredOutputError(str(exc)) from None
        return SimpleNamespace(value=value)


def test_compose_prose_gets_the_wording_check():
    res = result([("sex", "VARCHAR"), ("rate", "DOUBLE")], [["female", 0.727], ["male", 0.191]])

    def composed(prose):
        llm = OneReply({"prose": prose, "shape": "table", "number": None, "label": None, "chart": None})
        return comp.compose(llm, None, "survival by sex", [res], ["sex", "rate"], 1, None)

    blocks, by_model = composed([{"text": "Women survived at "}, {"chip": "r1:0:1"}, {"text": ", men at "}, {"chip": "r1:1:1"}])
    assert by_model and blocks[0]["type"] == "text"
    for words in ("Women survived about twice as often, at ", "Being a woman leads to survival at "):
        blocks, by_model = composed([{"text": words}, {"chip": "r1:0:1"}])
        assert not by_model and blocks[0]["type"] == "table"  # the fallback: the rows with their source
