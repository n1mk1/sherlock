"""The chat agent v1 (TRD §8, §4.9, §5.3) on the sample, with recorded model replies."""

import json
from pathlib import Path

import pytest

from sherlock.agent import compose as comp
from sherlock.agent.answerers import Result
from sherlock.agent.resolve import column
from sherlock.config import get_settings
from sherlock.eval import ask as ask_eval
from tests.test_jobs import db_rows, wait_status

API = "/api/v1"
FIXTURE = Path(__file__).parent / "fixtures" / "llm" / "chat_titanic.json"
pytestmark = pytest.mark.usefixtures("run_jobs")


@pytest.fixture(autouse=True)
def mocked(monkeypatch):
    """Before the app is made, so its settings carry the fixture file."""
    monkeypatch.setenv("LLM_MOCK", str(FIXTURE))
    get_settings.cache_clear()


@pytest.fixture
def ready(client):
    ds = client.post(f"{API}/datasets/sample").json()
    wait_status(client, ds["id"], "offer")
    client.post(f"{API}/datasets/{ds['id']}/use-as-is")
    wait_status(client, ds["id"], "ready")
    return ds


def send(client, ds_id, text, **extra):
    """(events, final message) from the chat stream."""
    events, event = [], None
    with client.stream("POST", f"{API}/datasets/{ds_id}/chat", json={"text": text, "context": {"tab": "dashboard"}, **extra}) as r:
        assert r.status_code == 200, r.read()
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: "):
                events.append((event, json.loads(line[6:])))
    message = next(d for e, d in events if e == "message")
    return events, message


def blocks_of(message, kind):
    return [b for b in message["blocks"] if b["type"] == kind]


def test_ask_data_streams_a_table_then_a_grounded_answer(client, ready):
    events, msg = send(client, ready["id"], "average fare by class")
    kinds = [e for e, _ in events]
    assert kinds[0] == "status" and kinds.index("block") < kinds.index("message") and kinds[-1] == "message"
    table = blocks_of(msg, "table")[0]
    assert [c["name"] for c in table["columns"]] == ["pclass", "avg_fare"] and table["total"] == 3
    text = blocks_of(msg, "text")[0]["body"]["blocks"][0]["runs"]
    chip = next(r for r in text if r["type"] == "chip")
    assert chip["key"] == "r1:0:1" and chip["value"] == "87.51" and chip["raw"] == pytest.approx(87.509, rel=1e-4)
    assert msg["text"] == "First class paid the most on average, 87.51."
    sql = msg["sources"][0]["sql"]
    assert "_quarantine_reason IS NULL" in sql and sql.endswith("LIMIT 2000")
    assert "reading class → pclass" in msg["sources"][0]["label"]

    # The follow-up sees the previous question and its query (the fixture only matches if it does).
    _, follow = send(client, ready["id"], "and for women only?")
    chart = blocks_of(follow, "chart")[0]
    assert chart["spec"]["view"]["type"] == "bar" and chart["spec"]["op"]["sql"].count("{{rows}}") == 1
    assert {"kind": "pin", "block_index": follow["blocks"].index(chart)} in follow["actions"]

    thread = client.get(f"{API}/datasets/{ready['id']}/chat").json()
    assert [m["role"] for m in thread] == ["user", "assistant", "user", "assistant"]
    assert thread[1]["blocks"] == msg["blocks"]
    older = client.get(f"{API}/datasets/{ready['id']}/chat", params={"before": thread[2]["id"]}).json()
    assert [m["id"] for m in older] == [thread[0]["id"], thread[1]["id"]]
    calls = db_rows("SELECT purpose, role FROM llm_calls WHERE dataset_id = ? AND message_id IS NOT NULL", ready["id"])
    assert [(c["purpose"], c["role"]) for c in calls][:3] == [("route", "small"), ("sql", "medium"), ("compose", "medium")]


def test_number_answer_and_compose_fallback(client, ready):
    _, msg = send(client, ready["id"], "how many passengers survived?")
    number = blocks_of(msg, "number")[0]
    assert number["value"] == 500 and number["formatted"] == "500" and number["label"] == "passengers who survived"
    assert msg["text"] == "500 passengers survived."  # the full stop is added

    # Digits in a text run fail validation twice: the raw result is shown with its source.
    _, msg = send(client, ready["id"], "how many children?")
    assert msg["blocks"] == [{**blocks_of(msg, "number")[0]}]
    assert msg["blocks"][0]["value"] == 154 and msg["sources"][0]["sql"]


def test_find_rows_saves_a_selection(client, ready):
    _, msg = send(client, ready["id"], "which passengers paid more than 500?")
    table = blocks_of(msg, "table")[0]
    assert table["total"] == 4 and table["selection_id"] and len(table["rows"]) == 4
    assert msg["text"] == "4 rows match."
    assert {"kind": "open_rows", "selection_id": table["selection_id"]} in msg["actions"]
    rows = client.get(f"{API}/datasets/{ready['id']}/rows", params={"selection": table["selection_id"]}).json()
    assert rows["total"] == 4 and all(r["cells"]["fare"] > 500 for r in rows["rows"])


def test_create_widget_from_chat_and_from_the_add_drawer(client, ready):
    before = len(client.get(f"{API}/datasets/{ready['id']}/widgets").json()["widgets"])
    _, msg = send(client, ready["id"], "add a chart of fare by port to the dashboard")
    action = next(a for a in msg["actions"] if a["kind"] == "open_widget")
    widgets = client.get(f"{API}/datasets/{ready['id']}/widgets").json()
    assert len(widgets["widgets"]) == before + 1
    made = next(w for w in widgets["widgets"] if w["id"] == action["widget_id"])
    assert made["created_by"] == "chat" and made["title"] == "Average fare by port"
    assert widgets["layout"]["lg"][-1]["i"] == made["id"]
    assert "reading port → embarked" in msg["sources"][0]["label"]

    r = client.post(f"{API}/datasets/{ready['id']}/widgets", json={"prompt": "a KPI of the average age"})
    assert r.status_code == 201, r.text
    assert r.json()["widget"]["spec"]["view"]["type"] == "kpi" and r.json()["widget"]["created_by"] == "user"


def test_a_chart_answer_doesnt_add_a_widget_unasked(client, ready):
    before = len(client.get(f"{API}/datasets/{ready['id']}/widgets").json()["widgets"])
    _, msg = send(client, ready["id"], "survival rate by sex as a chart")  # routed to ask_data and create_widget
    assert blocks_of(msg, "chart") and not any(a["kind"] == "open_widget" for a in msg["actions"])
    assert len(client.get(f"{API}/datasets/{ready['id']}/widgets").json()["widgets"]) == before
    assert not db_rows("SELECT 1 FROM llm_calls WHERE dataset_id = ? AND purpose = 'widget'", ready["id"])


def test_clarification_then_the_choice(client, ready):
    _, ask = send(client, ready["id"], "compare the groups")
    assert ask["clarification"] == {"question": "Which groups?", "options": ["men and women", "the passenger classes"]}
    assert ask["blocks"] == []
    _, msg = send(client, ready["id"], "men and women", clarification_of=ask["id"], choice="men and women")
    assert msg["text"].startswith("Women survived at 72.7%") and "men at 19.1%" in msg["text"]


def test_honest_limits(client, ready):
    _, msg = send(client, ready["id"], "make this a line chart")  # update_widget (D8.5) with no widget in view
    assert msg["text"].startswith("Which widget?")
    titles = {w["title"] for w in client.get(f"{API}/datasets/{ready['id']}/widgets").json()["widgets"]}
    assert 2 <= len(msg["clarification"]["options"]) <= 3 and set(msg["clarification"]["options"]) <= titles  # ASK-6
    _, msg = send(client, ready["id"], "nationality breakdown")
    assert msg["text"].startswith("This file has no column that answers that.")
    assert "passengers by home destination" in msg["text"]
    _, msg = send(client, ready["id"], "what did cleaning change?")
    assert "Step 1: Typed" in msg["text"] and msg["sources"][0]["kind"] == "step"


def test_pin_a_chart_answer(client, ready):
    send(client, ready["id"], "average fare by class")
    _, msg = send(client, ready["id"], "and for women only?")
    index = next(a["block_index"] for a in msg["actions"] if a["kind"] == "pin")
    r = client.post(f"{API}/messages/{msg['id']}/pin", json={"target": "dashboard", "block_index": index})
    assert r.status_code == 201, r.text
    w = r.json()
    assert w["created_by"] == "chat" and w["title"] == "and for women only?"
    data = client.get(f"{API}/widgets/{w['id']}/data").json()
    assert data["rows"][0][1] == pytest.approx(109.41, rel=1e-3)
    assert client.post(f"{API}/messages/{msg['id']}/pin", json={"target": "flow", "block_index": index}).status_code == 422


def test_model_unavailable_and_not_ready(client):
    ds = client.post(f"{API}/datasets/sample").json()
    assert client.post(f"{API}/datasets/{ds['id']}/chat", json={"text": "hi"}).status_code == 409  # profiling
    wait_status(client, ds["id"], "offer")
    events, msg = send(client, ds["id"], "a question with no recorded reply")  # the model call fails
    assert msg["text"].startswith("The model service is unavailable")
    assert ("error", {"code": "llm_unavailable", "message": "The model service is unavailable. Try again in a minute."}) in events


def test_resolution_and_formatting():
    cols = ["pclass", "age", "fare", "home.dest"]
    assert column("average fare", cols) is None  # whole-string match: not "age"
    assert column("Home Dest", cols) == "home.dest" and column("PClass", cols) == "pclass"
    assert comp.fmt(0.7274, comp.fmt_kind(0.7274, "survival_rate")) == "72.7%"
    assert comp.fmt(1025982.16, "num") == "1,025,982" and comp.fmt(87.509, "num") == "87.51"
    res = Result("r1", "sql", "tpl", [{"name": "n", "type": "BIGINT"}], [[5]], 1)
    with pytest.raises(ValueError):
        comp.resolve_chip("r1:3:0", {"r1": res})
    assert comp.resolve_chip("r1:total", {"r1": res})[0] == 1


def test_a_value_label_must_be_a_value_the_answer_or_the_data_has():
    """Rule 2 (Day 6 review F2): a `value:` label is shown as written, so "fare 512.33" or
    "three quarters" as a label would put a number the model made up into the answer."""
    from sherlock.llm.schemas import ChipRun, LabelRun, TextRun

    res = Result("r1", "sql", "tpl", [{"name": "class", "type": "BIGINT"}, {"name": "avg_fare", "type": "DOUBLE"},
                                      {"name": "port", "type": "VARCHAR"}],
                 [[1, 87.51, "C"], [3, 13.3, "S"]], 2)
    cols = ["pclass", "fare", "sex", "embarked"]
    known = {"sex": ["male", "female"], "embarked": ["S", "Q"]}

    def shown(label, known=known):
        runs = comp.to_runs([TextRun(text="The highest is "), LabelRun(label=label), TextRun(text=" at "), ChipRun(chip="r1:0:1")],
                            {"r1": res}, cols, known)
        return runs[1]["text"]

    assert shown("value:embarked:C") == "C"  # a cell of one of the result's text columns
    assert shown("value:sex:female") == "female" and shown("value:embarked:Q") == "Q"  # values the DataCard knows
    for label in ("value:fare:512.33", "value:sex:three quarters", "value:embarked:female"):
        with pytest.raises(ValueError, match="no result shows"):
            shown(label)
    # Plan 2.9 (PRD STORY-8): a number column's cells are chips, never labels, so an average can't pass as a name.
    for label in ("value:fare:87.51", "value:pclass:1"):
        with pytest.raises(ValueError, match="no result shows"):
            shown(label)
    assert shown("value:pclass:1", known={**known, "pclass": ["3", "1", "2"]}) == "1"  # a code the DataCard knows


def test_eval_checks():
    msg = {"blocks": [{"type": "table", "columns": [], "rows": [[1, 87.5], [2, 21.18]], "total": 2}], "sources": [{"sql": "x"}]}
    assert ask_eval.check(msg, {"rows": {"1": 87.509, "2": 21.179}})[0]
    # The measure before the category (live, "Revenue by region" listed revenue first) still matches.
    flipped = {"blocks": [{"type": "table", "columns": [], "rows": [[104063.01, "Central"], [198168.56, "East"]], "total": 2}]}
    assert ask_eval.check(flipped, {"rows": {"Central": 104063.01, "East": 198168.56}})[0]
    assert not ask_eval.check(flipped, {"rows": {"Central": 198168.56, "East": 104063.01}})[0]
    assert ask_eval.check({"blocks": [{"type": "number", "value": 38.2}]}, {"value": 0.38197, "tol": 0.01})[0]
    assert not ask_eval.check({"blocks": [{"type": "number", "value": 12}]}, {"value": 13})[0]
    assert ask_eval.unsourced({"blocks": [{"type": "number", "value": 1}], "sources": []})
    questions = ask_eval.load()
    assert sum(len(q) for q in questions.values()) == 61  # D8.4: about fifty, every ASK-2 area; 11 more from the live test
    assert ask_eval.check({"text": "See Undo in the help.", "sources": [{"kind": "help"}], "blocks": []},
                          {"source": "help", "text_any": ["undo"]})[0]
    assert not ask_eval.check({"text": "x", "sources": [{"kind": "sql"}], "blocks": []}, {"source": "run"})[0]
    assert not ask_eval.unsourced({"blocks": [{"type": "table", "rows": []}], "sources": [{"kind": "run", "run_id": "r"}]})


def test_a_message_past_its_time_budget_makes_no_model_call(client, ready, monkeypatch):
    # Plan 0.3: the 90 s budget is the calls' deadline, so no call starts (or retries) past it.
    from sherlock.agent import loop

    monkeypatch.setattr(loop, "WALL_S", 0.0)
    before = len(db_rows("SELECT id FROM llm_calls WHERE dataset_id = ?", ready["id"]))
    events, msg = send(client, ready["id"], "average fare by class")
    assert msg["text"] == "This answer ran out of time."
    assert ("error", {"code": "llm_unavailable", "message": "This answer ran out of time."}) in events
    assert len(db_rows("SELECT id FROM llm_calls WHERE dataset_id = ?", ready["id"])) == before


def test_an_answer_card_reruns_its_queries_when_its_columns_change(client, ready):
    """Plan 2b.2 (TRD §7.6 `rerun_fact_sql`): an answer card added to Flow is checked by the cascade. A
    change it doesn't read leaves it alone; one it reads re-runs its stored query, and numbers that moved
    make it outdated, since its words were written about the old ones. Refresh takes the new numbers."""
    from tests.test_jobs import wait_for

    ds = ready["id"]

    def settled():
        return wait_for(lambda: (js := client.get(f"{API}/jobs?dataset_id={ds}").json())
                        and all(j["status"] in ("done", "failed", "cancelled") for j in js) and js, timeout=120)

    def edit(column, value, row=1):
        v = client.get(f"{API}/datasets/{ds}").json()["current_version"]
        r = client.post(f"{API}/datasets/{ds}/edits", json={"base_version": v, "edits": [{"row_id": row, "column": column,
                                                                                           "value": value}]})
        assert r.status_code == 201, r.text
        return r.json()["version"]

    settled()
    _, msg = send(client, ds, "average fare by class")
    action = next(a for a in msg["actions"] if a["kind"] == "add_to_flow")
    added = client.post(f"{API}/messages/{msg['id']}/pin", json={"target": "flow", "block_index": action["block_index"]})
    assert added.status_code == 201, added.text
    answer = added.json()
    sheet = client.get(f"{API}/fact-sheets/{answer['fact_sheet_id']}").json()
    assert "fare" in sheet["depends_columns"]

    edit("embarked", "Q", row=2)  # a column its query doesn't read
    jobs = settled()
    cascade = next(j for j in jobs if j["kind"] == "cascade")
    assert cascade["result"]["answers"]["checked"] == 0
    assert client.get(f"{API}/cards/{answer['id']}").json()["status"] == "ready"

    edit("fare", "999")  # one it reads: an average moves
    jobs = settled()
    cascade = next(j for j in jobs if j["kind"] == "cascade")
    assert cascade["result"]["answers"] == {"checked": 1, "kept": 0, "outdated": 1}, cascade["result"]
    stale = client.get(f"{API}/cards/{answer['id']}").json()
    assert stale["status"] == "outdated" and stale["facts"] == answer["facts"]  # the old numbers beside the old words

    job = client.post(f"{API}/cards/{answer['id']}/refresh")
    assert job.status_code == 201, job.text
    settled()
    fresh = client.get(f"{API}/cards/{answer['id']}").json()
    assert fresh["status"] == "ready" and fresh["changed_badge"] and fresh["facts"] != answer["facts"]
    assert fresh["version"] == client.get(f"{API}/datasets/{ds}").json()["current_version"]
