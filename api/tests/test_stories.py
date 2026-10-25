"""Story cards (TRD §7.4, §7.6; PRD STORY-1–STORY-8): fact sheets in code, the narrator's checks,
cards and evidence, edits, and the cascade re-narrating only the cards that depend on what changed."""

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from sherlock.config import get_settings
from sherlock.llm.schemas import ChipRun, LabelRun, Story, TextRun
from sherlock.stories import facts as fx
from sherlock.stories import narrate as nr
from sherlock.stories.service import mark_unverified
from tests.test_jobs import db_rows, wait_for, wait_status

API = "/api/v1"
FIXTURE = Path(__file__).parent / "fixtures" / "llm" / "stories_titanic.json"


def conn_with(df: pd.DataFrame) -> duckdb.DuckDBPyConnection:
    c = duckdb.connect()
    c.register("src", df)
    c.execute("CREATE TABLE t AS SELECT * FROM src")
    return c


def test_facts_for_a_rate_by_group_with_a_chi2_test():
    df = pd.DataFrame({"_quarantine_reason": [None] * 200, "sex": ["f"] * 100 + ["m"] * 100,
                       "survived": [1] * 70 + [0] * 30 + [1] * 20 + [0] * 80})
    conn = conn_with(df)
    sql = "SELECT sex, AVG(survived) AS rate, COUNT(*) AS n FROM t WHERE _quarantine_reason IS NULL AND (1=1) GROUP BY 1 ORDER BY 2 DESC"
    rows = conn.execute(sql).fetchall()
    src = fx.Source(sql=sql, rows_sql="_quarantine_reason IS NULL AND (1=1)",
                    spec={"scope": {"columns": {"x": "sex", "y": "survived", "agg": "rate"}},
                          "view": {"type": "bar", "options": {"x": "sex", "y": "rate", "label_format": "pct"}}},
                    title="Survival by sex", columns=[{"name": "sex", "type": "VARCHAR"}, {"name": "rate", "type": "DOUBLE"},
                                                      {"name": "n", "type": "BIGINT"}], rows=[list(r) for r in rows])
    f = fx.compute(conn, src)
    assert (f["top_group"]["value"], f["top_value"]["formatted"], f["bottom_value"]["formatted"]) == ("f", "70.0%", "20.0%")
    assert f["ratio_top_bottom"]["formatted"] == "3.5×"
    assert f["overall"]["formatted"] == "45.0%" and f["n"]["value"] == 200
    assert f["significance"]["value"] == "p<0.001" and f["significance"]["method"] == "chi2"
    assert 0.4 < f["effect"]["value"] < 0.6
    assert fx.verify(conn, f, list(f)) == []
    conn.execute("UPDATE t SET survived = 1 WHERE sex = 'm'")  # the data moved under the sheet
    assert set(fx.verify(conn, f, list(f))) >= {"bottom_value", "n"} - {"n"}
    assert fx.depends_on(src.spec, sql) == ["sex", "survived"]


def test_facts_for_a_trend_and_a_kpi():
    df = pd.DataFrame({"_quarantine_reason": [None] * 6, "m": pd.date_range("2024-01-01", periods=6, freq="MS"),
                       "v": [1.0, 2, 3, 4, 5, 6]})
    conn = conn_with(df)
    sql = "SELECT m, SUM(v) AS total FROM t WHERE _quarantine_reason IS NULL AND (1=1) GROUP BY 1 ORDER BY 1"
    rows = [list(r) for r in conn.execute(sql).fetchall()]
    src = fx.Source(sql=sql, rows_sql="_quarantine_reason IS NULL AND (1=1)",
                    spec={"scope": {"columns": {"x": "m", "y": "v", "agg": "sum"}}, "view": {"type": "line", "options": {"y": "total"}}},
                    title="Total by month", columns=[{"name": "m", "type": "DATE"}, {"name": "total", "type": "DOUBLE"}], rows=rows)
    f = fx.compute(conn, src)
    assert f["trend"]["value"] == "rising" and f["change"]["formatted"] == "500.0%"
    assert f["peak_period"]["value"] == "2024-06-01"
    assert fx.small_sample(f)
    kpi = fx.Source(sql="SELECT 5 AS x", rows_sql="1=1", spec={"view": {"type": "kpi", "options": {"value": "x"}}},
                    title="Five", columns=[{"name": "x", "type": "INTEGER"}], rows=[[5]])
    assert fx.compute(conn, kpi)["value"]["formatted"] == "5"


FACTS = {"top_value": {"value": 0.7, "formatted": "70.0%", "label": "rate"}, "n": {"value": 20, "formatted": "20", "label": "rows"}}


@pytest.mark.parametrize("runs, error", [
    ([TextRun(text="Women did "), ChipRun(chip="nope"), TextRun(text=" better.")], "names no fact"),
    ([TextRun(text="the rate is {\"chip\": \"n\"} here")], "markup"),
    ([LabelRun(label="column:ghost"), TextRun(text=" is high.")], "names no column"),
])
def test_runs_are_checked(runs, error):
    with pytest.raises(ValueError, match=error):
        nr.to_runs(runs, FACTS, ["sex"])


def test_digits_never_reach_a_text_run_and_runs_are_spaced():
    with pytest.raises(ValueError):
        Story.model_validate({"headline": [{"text": "Women were 3 times as likely"}], "body": [{"text": "x y"}]})
    runs = nr.to_runs([TextRun(text="Women survived at"), ChipRun(chip="top_value"), TextRun(text="of the time.It held.")],
                      FACTS, ["sex"])
    assert "".join(r.get("value") or r.get("text") for r in runs) == "Women survived at 70.0% of the time. It held."


def test_narrate_falls_back_to_bullets_and_checks_wording():
    class Fake:
        def __init__(self, story):
            self.story = story

        def structured(self, role, messages, schema, *, purpose, scope, validate):
            from sherlock.llm.client import StructuredOutputError

            try:
                validate(self.story)
            except ValueError as exc:
                raise StructuredOutputError(str(exc)) from exc
            return type("S", (), {"value": self.story})()

    causal = Story(headline=[TextRun(text="Being a woman leads to survival")],
                   body=[TextRun(text="The rate is "), ChipRun(chip="top_value"), TextRun(text=" for women.")])
    h, b, by_model = nr.narrate(Fake(causal), None, title="Survival by sex", widget_id="w1", spec={}, facts=FACTS,
                                widget_columns=["sex"], dataset_columns=["sex"], related=[])
    assert not by_model and b["blocks"][0]["type"] == "bullets"
    assert h["blocks"][0]["runs"][0] == {"type": "label", "ref": "widget:w1", "text": "Survival by sex"}
    plain = Story(headline=[TextRun(text="Women fared better in this small sample")],
                  body=[TextRun(text="The rate is "), ChipRun(chip="top_value"), TextRun(text=" for women in a small sample.")])
    h, b, by_model = nr.narrate(Fake(plain), None, title="t", widget_id="w1", spec={}, facts=FACTS,
                                widget_columns=["sex"], dataset_columns=["sex"], related=[])
    assert by_model and b["blocks"][0]["runs"][1]["value"] == "70.0%"
    no_note = Story(headline=[TextRun(text="Women fared better here")],
                    body=[TextRun(text="The rate is "), ChipRun(chip="top_value"), TextRun(text=" for women.")])
    assert not nr.narrate(Fake(no_note), None, title="t", widget_id="w1", spec={}, facts=FACTS,
                          widget_columns=["sex"], dataset_columns=["sex"], related=[])[2]  # n = 20 needs the note
    spelled = Story(headline=[TextRun(text="Women did twice as well in this small sample")],
                    body=[TextRun(text="The rate is "), ChipRun(chip="top_value"), TextRun(text=" for women in a small sample.")])
    assert not nr.narrate(Fake(spelled), None, title="t", widget_id="w1", spec={}, facts=FACTS,
                          widget_columns=["sex"], dataset_columns=["sex"], related=[])[2]  # "twice" is a number


def test_a_heatmap_story_may_name_both_categories_of_its_cell():
    facts = {"max_x": fx.fact("1", "text", "pclass of the highest cell"), "max_y": fx.fact("female", "text", "sex of the highest cell")}
    spec = {"scope": {"columns": {"x": "pclass", "series": "sex", "y": "survived"}}}
    assert {"value:pclass:1", "value:sex:female"} <= set(nr.allowed_labels(["pclass", "sex", "survived"], facts, spec))


def test_hand_typed_numbers_become_unverified_chips():
    body = mark_unverified({"blocks": [{"type": "paragraph", "runs": [{"type": "text", "text": "About 75% of 1,200 survived."}]}]})
    runs = body["blocks"][0]["runs"]
    assert [r["type"] for r in runs] == ["text", "chip", "text", "chip", "text"]
    assert runs[1] == {"type": "chip", "id": "u1", "key": None, "value": "75%", "unverified": True}


@pytest.fixture
def mocked(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", str(FIXTURE))
    get_settings.cache_clear()


def _ready_with_stories(client):
    ds = client.post(f"{API}/datasets/sample").json()
    wait_status(client, ds["id"], "offer")
    client.post(f"{API}/datasets/{ds['id']}/use-as-is")
    wait_status(client, ds["id"], "ready")
    wait_for(lambda: any(j["kind"] == "stories" and j["status"] == "done"
                         for j in client.get(f"{API}/jobs?dataset_id={ds['id']}").json()), timeout=60)
    # The driver widget's run (TRD §7.3 step 5) queues its own story when it finishes.
    wait_for(lambda: all(j["status"] in ("done", "failed", "cancelled")
                         for j in client.get(f"{API}/jobs?dataset_id={ds['id']}").json()), timeout=120)
    return ds["id"]


@pytest.mark.usefixtures("run_jobs")
def test_stories_job_cards_evidence_and_edits(mocked, client):
    ds = _ready_with_stories(client)
    cards = client.get(f"{API}/datasets/{ds}/cards").json()
    widgets = client.get(f"{API}/datasets/{ds}/widgets").json()["widgets"]
    assert cards[0]["kind"] == "overview" and len(cards) == len(widgets) + 1
    assert all(c["narrated_by"] for c in cards), [c["narrated_by"] for c in cards]
    titles = {w["id"]: w["title"] for w in widgets}
    sex = next(c for c in cards if c["kind"] == "widget" and titles[c["widget_id"]] == "Fare by passenger class")
    chips = [r for b in sex["headline"]["blocks"] + sex["body"]["blocks"] for r in b["runs"] if r["type"] == "chip"]
    assert chips and all(sex["facts"][r["key"]]["formatted"] == r["value"] for r in chips)
    ev = client.get(f"{API}/cards/{sex['id']}/evidence/{chips[0]['id']}").json()
    assert ev["sql"] and "{{rows}}" not in ev["sql"] and ev["version"] >= 2
    assert sex["related"], "the class widget shares fare with the fare widgets"
    edges = client.get(f"{API}/datasets/{ds}/relations").json()["edges"]
    assert edges and all(e["weight"] >= 0.4 for e in edges)

    edited = client.patch(f"{API}/cards/{sex['id']}", json={"body": {"blocks": [{"type": "paragraph", "runs": [
        {"type": "text", "text": "Women did far better, about 73%."}]}]}}).json()
    assert edited["edited_by_user"] and edited["body"]["blocks"][0]["runs"][1]["unverified"]
    ev = client.get(f"{API}/cards/{sex['id']}/evidence/u1").json()
    assert ev["unverified"] and ev["value"] == "73%"
    assert client.post(f"{API}/cards/{sex['id']}/dismiss-badge").json()["changed_badge"] is False


@pytest.mark.usefixtures("run_jobs")
def test_the_cascade_retells_only_the_cards_that_depend_on_the_change(mocked, client):
    ds = _ready_with_stories(client)
    cards = {c["widget_id"]: c for c in client.get(f"{API}/datasets/{ds}/cards").json() if c["kind"] == "widget"}
    widgets = {w["id"]: w for w in client.get(f"{API}/datasets/{ds}/widgets").json()["widgets"]}
    fare = {wid for wid, w in widgets.items() if w["spec"]["op"]["type"] == "sql" and "fare" in w["spec"]["op"]["sql"]}
    ml = {wid for wid, w in widgets.items() if w["spec"]["op"]["type"] == "ml"}  # the driver widget uses fare too
    sex_card = next(c for c in cards.values() if "Survival rate" == widgets[c["widget_id"]]["title"])
    client.patch(f"{API}/cards/{sex_card['id']}", json={"headline": {"blocks": [{"type": "paragraph", "runs": [
        {"type": "text", "text": "My own headline"}]}]}})
    fare_card = next(c for c in cards.values() if "Fare by passenger class" == widgets[c["widget_id"]]["title"])
    client.patch(f"{API}/cards/{fare_card['id']}", json={"headline": {"blocks": [{"type": "paragraph", "runs": [
        {"type": "text", "text": "My fare headline"}]}]}})
    v = client.get(f"{API}/datasets/{ds}").json()["current_version"]
    saved = client.post(f"{API}/datasets/{ds}/edits", json={"base_version": v, "edits": [
        {"row_id": 1, "column": "fare", "value": "500"}]})
    assert saved.status_code == 201
    done = wait_for(lambda: next((j for j in client.get(f"{API}/jobs?dataset_id={ds}").json()
                                  if j["kind"] == "cascade" and j["status"] in ("done", "failed")), None), timeout=60)
    assert done["status"] == "done", done
    # The driver widget's run is outdated and re-runs ("Story updates: Automatic"); its card waits for the new run.
    assert done["result"]["widgets"] == len(fare) + len(ml) and done["result"]["cards"] == len(fare)
    assert done["result"]["runs"] == len(ml) == 1
    after = {c["widget_id"]: c for c in client.get(f"{API}/datasets/{ds}/cards").json() if c["kind"] == "widget"}
    for wid, c in after.items():
        assert c["changed_badge"] == (wid in fare), widgets[wid]["title"]
    assert after[sex_card["widget_id"]]["suggestion"] is None  # survival doesn't read fare: no suggestion
    kept = after[fare_card["widget_id"]]
    assert kept["headline"]["blocks"][0]["runs"][0]["text"] == "My fare headline" and kept["suggestion"]["body"]
    started = db_rows("SELECT data_json FROM job_events WHERE dataset_id = ? AND type = 'cascade.started'", ds)
    assert '"fare"' in started[-1]["data_json"]
    accepted = client.post(f"{API}/cards/{kept['id']}/accept-suggestion").json()
    current = client.get(f"{API}/datasets/{ds}").json()["current_version"]
    assert not accepted["edited_by_user"] and accepted["version"] == current and accepted["suggestion"] is None


@pytest.mark.usefixtures("run_jobs")
def test_a_card_whose_query_fails_is_not_left_updating(mocked, client, monkeypatch):
    from sherlock.errors import ApiError
    from sherlock.stories import service

    ds = _ready_with_stories(client)
    card = next(c for c in client.get(f"{API}/datasets/{ds}/cards").json() if c["kind"] == "widget")
    real = service.build_sheet

    def failing(env, dataset, widget, version):
        if widget["id"] == card["widget_id"]:
            raise ApiError(422, "invalid", "query failed")
        return real(env, dataset, widget, version)

    monkeypatch.setattr(service, "build_sheet", failing)
    job = client.post(f"{API}/cards/{card['id']}/refresh").json()
    wait_for(lambda: client.get(f"{API}/jobs/{job['id']}").json()["status"] in ("done", "failed"), timeout=60)
    after = client.get(f"{API}/cards/{card['id']}").json()
    assert after["status"] == "outdated" and after["headline"] == card["headline"]


@pytest.mark.usefixtures("run_jobs")
def test_cards_go_into_the_notebook(mocked, client):
    import nbformat

    from tests.test_notebook import _export

    ds = _ready_with_stories(client)
    cards = client.get(f"{API}/datasets/{ds}/cards").json()
    out = _export(client, ds)
    assert out["counts"]["cards"] == len(cards)
    nb = nbformat.reads(client.get(out["download_url"]).text, as_version=4)
    md = [c.source for c in nb.cells if c.cell_type == "markdown"]
    assert any(m.startswith("## What stands out") for m in md)
    for c in cards:
        for b in c["body"]["blocks"]:
            for r in b["runs"]:
                if r["type"] == "chip":
                    assert any(c["facts"][r["key"]]["formatted"] in m for m in md)
    assert any("<details><summary>Evidence</summary>" in m for m in md)
    nbformat.validate(nb)


def test_labels_and_brackets_read_naturally():
    runs = nr.to_runs([TextRun(text="The "), LabelRun(label="value:pclass:1"), TextRun(text=" group pays more ( "),
                       ChipRun(chip="top_value"), TextRun(text=" )")], FACTS, ["pclass"])
    assert "".join(r.get("value") or r.get("text") for r in runs) == "The pclass 1 group pays more (70.0%)."


def test_no_number_reaches_a_card_by_another_way():
    """Rule 2 (Day 6 review): a value label the facts don't name, a number spelled another way,
    a Unicode number or an HTML entity is refused like a digit."""
    class Fake:
        def __init__(self, story):
            self.story = story

        def structured(self, role, messages, schema, *, purpose, scope, validate):
            from sherlock.llm.client import StructuredOutputError

            try:
                validate(self.story)
            except ValueError as exc:
                raise StructuredOutputError(str(exc)) from exc
            return type("S", (), {"value": self.story})()

    facts = {**FACTS, "n": {"value": 200, "formatted": "200", "label": "rows"},
             "top_group": {"value": "female", "formatted": "female", "label": "sex with the highest rate"}}
    spec = {"scope": {"columns": {"x": "sex", "y": "survived"}}}

    def told(body):
        story = Story(headline=[TextRun(text="Women fared better than men here")], body=body)
        return nr.narrate(Fake(story), None, title="t", widget_id="w1", spec=spec, facts=facts,
                          widget_columns=["sex", "survived"], dataset_columns=["sex", "survived", "fare"], related=[])[2]

    rate = [TextRun(text="The rate for "), LabelRun(label="value:sex:female"), TextRun(text=" was "), ChipRun(chip="top_value"),
            TextRun(text=" overall.")]
    assert told(rate)  # an allowed value label still passes
    for label in ("value:fare:512.33", "value:sex:three quarters"):
        assert not told([TextRun(text="Passengers paid about "), LabelRun(label=label), TextRun(text=" against "),
                         ChipRun(chip="top_value"), TextRun(text=" survival.")])
    for words in ("Seventeen men survived, against ", "About half of men survived, against ", "Over XLV men survived, against ",
                  "Survival quadrupled for women, at ", "One in a few men survived, against ", "A third of men survived, against ",
                  "Roughly &half; of women survived, at "):
        assert not told([TextRun(text=words), ChipRun(chip="top_value"), TextRun(text=" for women.")]), words
    for text in ("x²", "½ of men", "class ①", "Ⅻ cases"):
        with pytest.raises(ValueError):
            TextRun(text=text)

    # The overview takes only the value labels its widgets' facts name.
    widgets = [{"prefix": "w1", "title": "Survival by sex", "facts": facts, "score": 1, "widget_id": "w1", "spec": spec,
                "columns": ["sex", "survived"]}]

    class Over(Fake):
        pass

    good = nr.Overview(bullets=[[TextRun(text="Survival was highest for "), LabelRun(label="value:sex:female"),
                                 TextRun(text=" passengers, at "), ChipRun(chip="w1.top_value")]] * 2)
    assert nr.overview(Over(good), None, widgets, ["sex", "survived", "fare"])[2]
    bad = nr.Overview(bullets=[[TextRun(text="Passengers paid about "), LabelRun(label="value:fare:512.33"),
                                TextRun(text=" while survival was "), ChipRun(chip="w1.top_value")]] * 2)
    assert not nr.overview(Over(bad), None, widgets, ["sex", "survived", "fare"])[2]
