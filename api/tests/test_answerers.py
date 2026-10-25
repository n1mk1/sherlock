"""The D7.3 answerers (TRD §8.2) on the sample, with model replies recorded live on 2026-10-25:
`ask_stats`, `ask_why`, `ask_model` (with "who did it get wrong?"), `ask_meaning`, `app_help`, and
tool exposure by tab. Every number in these answers is a chip filled in by code."""

import pytest

from sherlock.agent import insight
from sherlock.agent.answerers import CantAnswer
from sherlock.agent.loop import TOOLS
from tests.test_chat import FIXTURE, blocks_of, send  # noqa: F401 - the fixture file and helpers
from tests.test_chat import mocked, ready  # noqa: F401 - pytest fixtures
from tests.test_jobs import wait_for

API = "/api/v1"
pytestmark = pytest.mark.usefixtures("run_jobs")


def chips(message):
    return [r for b in blocks_of(message, "text") for p in b["body"]["blocks"] for r in p["runs"] if r["type"] == "chip"]


def driver_done(client, ds):
    widgets = client.get(f"{API}/datasets/{ds}/widgets").json()["widgets"]
    driver = next(w for w in widgets if w["spec"]["op"]["type"] == "ml")
    return wait_for(lambda: (r := client.get(f"{API}/runs/{driver['run_id']}").json())["status"] == "done" and r, timeout=120)


def test_ask_stats_picks_the_test_by_the_column_types(client, ready):
    _, msg = send(client, ready["id"], "is fare significantly different between men and women?")
    assert "Welch's t-test gives a p-value of" in msg["text"] and "Mann-Whitney U agrees" in msg["text"]
    table = blocks_of(msg, "table")[0]
    assert [c["name"] for c in table["columns"]] == ["test", "statistic", "p_value", "effect", "effect_size", "n"]
    assert table["rows"][0][0] == "Welch's t-test" and table["rows"][0][2] < 0.001
    assert (table["rows"][0][4] > 0) == (table["rows"][1][4] > 0)  # Cohen's d and the rank-biserial r agree in sign
    by_key = {c["key"]: c for c in chips(msg)}
    assert by_key[f"{table['result']}:0:5"]["raw"] == table["rows"][0][5]  # every number is a cell of the result
    groups = blocks_of(msg, "table")[1]
    assert [r[0] for r in groups["rows"]] == ["female", "male"]
    assert msg["sources"][0]["label"].startswith("The rows tested")


def test_ask_why_answers_from_the_cached_driver_run(client, ready):
    run = driver_done(client, ready["id"])
    _, msg = send(client, ready["id"], "what drives survival?")
    assert msg["text"].startswith("A model can predict survived better than simple rules")
    assert "The strongest factors are sex" in msg["text"] and "not causes" in msg["text"]
    assert {"kind": "open_model_card", "run_id": run["id"]} in msg["actions"]
    jobs = [j for j in client.get(f"{API}/jobs?dataset_id={ready['id']}").json() if j["kind"] == "ml_run"]
    assert len(jobs) == 1  # the builder's run, from the cache


def test_ask_model_and_who_it_got_wrong(client, ready):
    run = driver_done(client, ready["id"])
    _, msg = send(client, ready["id"], "how accurate is the model?")
    number = blocks_of(msg, "number")[0]
    assert number["formatted"] == f"{run['model_card']['model']['value'] * 100:.1f}%" and number["label"] == "model accuracy"
    assert {"kind": "open_model_card", "run_id": run["id"]} in msg["actions"]
    assert not blocks_of(msg, "chart") and not any(a["kind"] == "pin" for a in msg["actions"])

    _, msg = send(client, ready["id"], "who did the model get wrong?")
    wrong = run["model_card"]["misclassified"]
    assert msg["text"].startswith(f"The model got {wrong:,} of ")
    table = blocks_of(msg, "table")[0]
    assert table["total"] == wrong and table["selection_id"]
    assert {"kind": "open_rows", "selection_id": table["selection_id"]} in msg["actions"]
    page = client.get(f"{API}/datasets/{ready['id']}/rows", params={"selection": table["selection_id"]}).json()
    assert page["total"] == wrong


def test_ask_meaning_keeps_general_knowledge_apart(client, ready):
    _, msg = send(client, ready["id"], "what does sibsp mean?")
    assert msg["text"].startswith("sibsp is a whole-number column")
    general = [b for b in blocks_of(msg, "text") if b.get("labeled") == "general"]
    assert len(general) == 1 and "siblings" in general[0]["body"]["blocks"][0]["runs"][1]["text"]
    assert not any(ch.isdigit() for ch in general[0]["body"]["blocks"][0]["runs"][1]["text"])
    assert {c["key"].split(":")[0] for c in chips(msg)} == {blocks_of(msg, "table")[0]["result"][:-1]}  # the counts query
    assert msg["sources"][-1]["kind"] == "general"


def test_app_help_and_tool_exposure_by_tab(client, ready):
    _, msg = send(client, ready["id"], "how do I undo a step?")
    assert msg["text"].startswith("Undo a step: Open the CSV tab") and msg["sources"][0]["kind"] == "help"

    before = len(client.get(f"{API}/datasets/{ready['id']}/widgets").json()["widgets"])
    events, msg = send(client, ready["id"], "add a chart of fare by sex to the dashboard", context={"tab": "csv"})
    assert blocks_of(msg, "chart") and not any(a["kind"] == "open_widget" for a in msg["actions"])
    assert len(client.get(f"{API}/datasets/{ready['id']}/widgets").json()["widgets"]) == before
    assert "create_widget" in TOOLS["dashboard"] and "create_widget" not in TOOLS["csv"] and "ask_story" in TOOLS["flow"]


def test_help_retrieval_and_its_limits():
    reply = insight.app_help("how do I export a notebook?")
    assert reply.blocks[0]["body"]["blocks"][0]["runs"][0]["text"] == "Export a notebook"
    with pytest.raises(CantAnswer):
        insight.app_help("zzz qqq")
    assert insight._size(0.6, (0.2, 0.5, 0.8)) == "medium" and insight._p(0.0004) == "<0.001"


def test_ask_why_names_the_one_column_that_carries_the_signal():
    mc = {"verdict": "weak", "model": {"metric": "accuracy", "value": 0.83},
          "baselines": [{"name": "everyone gets the most common outcome", "value": 0.53},
                        {"name": "best one-column rule: x2", "value": 0.828, "column": "x2"}]}
    scores = insight.memory_result("r1m", "model card", [("measure", "VARCHAR"), ("value", "DOUBLE")],
                                   [["model accuracy", 0.83], ["best one-column rule: x2", 0.828]])
    runs = insight._verdict_runs(mc, "churned", "accuracy", lambda v: f"{v * 100:.1f}%", scores)
    words = "".join(r.get("text", r.get("value", "")) for r in runs)
    assert words.startswith("x2 alone predicts churned about as well as the model: accuracy 82.8% against 83.0%")
    assert "weak" not in words and [r["key"] for r in runs if r["type"] == "chip"] == ["r1m:1:1", "r1m:0:1"]
    mc["baselines"][1]["target_encoded"] = True  # a target-encoded ID (a ticket number) isn't named
    assert "".join(r.get("text", "") for r in insight._verdict_runs(mc, "churned", "accuracy", str, scores)).startswith("The signal is weak")
    mc["baselines"][1].pop("target_encoded")
    mc["baselines"][1]["value"] = 0.54  # no column stands out: the drivers are weak
    assert "".join(r.get("text", "") for r in insight._verdict_runs(mc, "churned", "accuracy", str, scores)).startswith("The signal is weak")
