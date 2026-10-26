"""Story cards (TRD §7.4, §7.6; PRD STORY-1–STORY-8): fact sheets in code, the narrator's checks,
cards and evidence, edits, and the cascade re-narrating only the cards that depend on what changed."""

import json
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
    # Plan 2b.7 (D6 F18): a number typed in words is a number too, but a Roman-looking size isn't.
    body = mark_unverified({"blocks": [{"type": "paragraph", "runs": [
        {"type": "text", "text": "Zero women in XL cabins paid twice the fare; one in three came back."}]}]})
    chips = [r["value"] for r in body["blocks"][0]["runs"] if r["type"] == "chip"]
    assert chips == ["Zero", "twice", "one in", "three"]


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
    sheet_version = ev["version"]
    assert sex["related"], "the class widget shares fare with the fare widgets"
    edges = client.get(f"{API}/datasets/{ds}/relations").json()["edges"]
    assert edges and all(e["weight"] >= 0.4 for e in edges)

    edited = client.patch(f"{API}/cards/{sex['id']}", json={"body": {"blocks": [{"type": "paragraph", "runs": [
        {"type": "text", "text": "Women did far better, about 73%."}]}]}}).json()
    assert edited["edited_by_user"] and edited["body"]["blocks"][0]["runs"][1]["unverified"]
    ev = client.get(f"{API}/cards/{sex['id']}/evidence/u1").json()
    assert ev["unverified"] and ev["value"] == "73%"
    assert client.post(f"{API}/cards/{sex['id']}/dismiss-badge").json()["changed_badge"] is False

    # Day 6 review F3: nothing the browser sends is taken on trust. A chip with a real key shows its
    # fact's value whatever value was sent; a chip with no fact behind it, or a pasted label that isn't
    # the card's or a column's, can't pass for computed.
    key = chips[0]["key"]
    forged = client.patch(f"{API}/cards/{sex['id']}", json={"body": {"blocks": [{"type": "paragraph", "runs": [
        {"type": "text", "text": "Fares: "}, {"type": "chip", "id": "p1", "key": key, "value": "999.99", "unverified": False},
        {"type": "text", "text": ", "}, {"type": "chip", "id": "p2", "key": "made_up", "value": "512.33", "unverified": False},
        {"type": "text", "text": ", "}, {"type": "chip", "id": "p3", "key": None, "value": "42", "unverified": False},
        {"type": "text", "text": " and "}, {"type": "label", "ref": "value:fare:7.25", "text": "7.25"},
        {"type": "text", "text": " for "}, {"type": "label", "ref": "column:fare", "text": "fare"}]}]}}).json()
    runs = forged["body"]["blocks"][0]["runs"]
    got = {r["id"]: r for r in runs if r["type"] == "chip"}
    assert got["p1"] == {"type": "chip", "id": "p1", "key": key, "value": sex["facts"][key]["formatted"], "unverified": False}
    assert got["p2"]["unverified"] and got["p2"]["key"] is None and got["p3"]["unverified"]
    assert any(r["type"] == "chip" and r["unverified"] and r["value"] == "7.25" for r in runs)  # the pasted label became typed text
    assert {"type": "label", "ref": "column:fare", "text": "fare"} in runs
    assert client.get(f"{API}/cards/{sex['id']}/evidence/p2").json()["unverified"]

    # Plan 2b.7: an edit records the version its words were written on, the sheet its chips read, not the
    # one Sherlock last wrote the card on (the web's "Written on vN, data is now vM" badge).
    db_rows("UPDATE cards SET version = 1 WHERE id = ?", sex["id"])
    again = client.patch(f"{API}/cards/{sex['id']}", json={"headline": {"blocks": [{"type": "paragraph", "runs": [
        {"type": "text", "text": "Fares by class, my words"}]}]}}).json()
    assert again["version"] == sheet_version


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


def test_the_overview_keeps_derived_facts_checkable():
    """Its merged sheet prefixes a derived fact's `from` like its key, so verify can recompute it (D8.4)."""
    from sherlock.stories.service import _Offline

    facts = {"top_value": {"value": 0.6, "formatted": "60%", "label": "top"},
             "bottom_value": {"value": 0.2, "formatted": "20%", "label": "bottom"},
             "ratio_top_bottom": {"value": 3.0, "formatted": "3.0×", "label": "ratio", "from": ["top_value", "bottom_value"],
                                  "formula": "a / b"}}
    merged, _, by_model = nr.overview(_Offline(), None, [{"prefix": "w1", "title": "A", "facts": facts, "score": 1,
                                                          "widget_id": "wdg_x"}], ["sex"])
    assert not by_model and merged["w1.ratio_top_bottom"]["from"] == ["w1.top_value", "w1.bottom_value"]
    assert fx.verify(duckdb.connect(), merged, ["w1.ratio_top_bottom"]) == []


def test_a_run_that_finishes_before_the_first_card_still_gets_its_story(client):
    """The race in the D9.1 seed: the build's stories job is running and no card exists yet when the
    analysis's run finishes; its widget's story must still be queued."""
    from sherlock.db.connection import connect
    from sherlock.db.util import new_id, now_iso
    from sherlock.widgets import service as ws
    from tests.test_jobs import upload

    ds = upload(client, b"a,b\n1,2\n")["id"]
    db = connect(client.app.state.settings)
    try:
        dataset = db.execute("SELECT * FROM datasets WHERE id = ?", (ds,)).fetchone()
        db.execute("INSERT INTO jobs (id, dataset_id, user_id, kind, status, params_json, created_at) "
                   "VALUES (?, ?, ?, 'stories', 'running', '{}', ?)", (new_id("job"), ds, dataset["user_id"], now_iso()))
        ws._stories(ws.Env(client.app.state.settings, db, None, None), dataset, ["wdg_analysis"])
        queued = db.execute("SELECT params_json FROM jobs WHERE dataset_id = ? AND kind = 'stories' AND status = 'queued'",
                            (ds,)).fetchone()
        assert queued and "wdg_analysis" in queued["params_json"]
    finally:
        db.close()


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


@pytest.mark.usefixtures("run_jobs")
def test_the_grounding_eval_checks_every_number_on_the_cards(mocked, client):
    import json

    from sherlock.db.connection import connect
    from sherlock.eval import grounding

    ds = _ready_with_stories(client)
    settings = get_settings()
    db = connect(settings)
    try:
        res = grounding.check_dataset(client, db, settings, "titanic3.csv", ds)
        assert res.cards >= 7 and res.chips > 0 and res.chips_ok == res.chips and res.problems == [], res.problems
        card = db.execute("SELECT * FROM cards WHERE dataset_id = ? AND kind = 'widget' AND narrated_by IS NOT NULL", (ds,)).fetchone()
        body = json.loads(card["body_json"])
        chip = next(r for b in body["blocks"] for r in b["runs"] if r["type"] == "chip")
        chip["value"] = "99.9%"  # a chip that no longer shows its fact
        body["blocks"].append({"type": "paragraph", "runs": [{"type": "text", "text": "Seventeen more survived."}]})
        db.execute("UPDATE cards SET body_json = ? WHERE id = ?", (json.dumps(body), card["id"]))
        db.commit()
        res = grounding.check_dataset(client, db, settings, "titanic3.csv", ds)
        assert len(res.problems) == 2 and res.chips_ok == res.chips - 1, res.problems
        assert "grounded" in grounding.report([res]).lower()
    finally:
        db.close()


def test_rows_behind_a_widget_have_its_columns_filled_and_cte_names_are_not_columns():
    """Day 6 review: "Average fare across 1,309 passengers" for an average over the 1,308 with a fare,
    and a histogram that "read" its own CTE's `lo` and `w`."""
    df = pd.DataFrame({"_quarantine_reason": [None] * 5, "fare": [1.0, 2.0, None, 4.0, 8.0], "sex": ["f", "m", "f", None, "m"]})
    conn = conn_with(df)
    rows = "_quarantine_reason IS NULL AND (1=1)"
    kpi = fx.Source(sql=f"SELECT AVG(fare) AS value, COUNT(fare) AS n FROM t WHERE {rows}", rows_sql=rows,
                    spec={"scope": {"columns": {"y": "fare", "agg": "avg"}}, "view": {"type": "kpi", "options": {"value": "value"}}},
                    title="Average fare", columns=[{"name": "value", "type": "DOUBLE"}, {"name": "n", "type": "BIGINT"}],
                    rows=[[3.75, 4]])
    f = fx.compute(conn, kpi)
    assert f["n"]["value"] == 4 and fx.verify(conn, f, ["n"]) == []
    by_sex = fx.Source(sql=f"SELECT sex, AVG(fare) AS v FROM t WHERE {rows} AND sex IS NOT NULL GROUP BY 1", rows_sql=rows,
                       spec={"scope": {"columns": {"x": "sex", "y": "fare", "agg": "avg"}}, "view": {"type": "bar", "options": {"y": "v"}}},
                       title="Fare by sex", columns=[{"name": "sex", "type": "VARCHAR"}, {"name": "v", "type": "DOUBLE"}],
                       rows=[["f", 1.0], ["m", 5.0]])
    assert fx.compute(conn, by_sex)["n"]["value"] == 3
    hist = ("WITH b AS (SELECT MIN(fare) AS lo, (MAX(fare) - MIN(fare)) / 20 AS w FROM t WHERE 1=1) "
            "SELECT b.lo + b.w * FLOOR((fare - b.lo) / b.w) AS bin_start, COUNT(*) AS n FROM t, b WHERE fare IS NOT NULL GROUP BY 1")
    assert fx.depends_on({"scope": {"columns": {"x": "fare"}}}, hist) == ["fare"]


def test_a_unit_the_chip_shows_is_not_said_twice_and_a_label_after_a_full_stop_gets_its_space():
    facts = {"rate": {"value": 0.382, "formatted": "38.2%", "label": "rate"}, "ratio": {"value": 3.8, "formatted": "3.8×", "label": "r"},
             "verdict": {"value": "Beats the rule.", "formatted": "Beats the rule.", "label": "v"}}

    def shown(runs):
        return "".join(r.get("value") or r.get("text") for r in nr.to_runs(runs, facts, ["sex"]))

    assert shown([TextRun(text="Survival rate was "), ChipRun(chip="rate"), TextRun(text="%.")]) == "Survival rate was 38.2%."
    assert shown([TextRun(text="Women were "), ChipRun(chip="ratio"), TextRun(text=" times as likely, at "), ChipRun(chip="rate"),
                  TextRun(text=" percent overall.")]) == "Women were 3.8× as likely, at 38.2% overall."
    assert shown([TextRun(text="The model says "), ChipRun(chip="verdict")]) == "The model says Beats the rule."
    assert shown([TextRun(text="It shows fare for each sex."), LabelRun(label="column:sex"), TextRun(text=" leads.")]) \
        == "It shows fare for each sex. sex leads."


@pytest.mark.usefixtures("run_jobs")
def test_ask_first_marks_the_affected_cards_outdated_without_narrating(mocked, client):
    """Day 6 review: "Story updates: Ask first" (TRD §7.6) had no test of its own for cards."""
    ds = _ready_with_stories(client)
    client.put(f"{API}/me/settings", json={"story_updates": "ask"})
    before = {c["widget_id"]: c for c in client.get(f"{API}/datasets/{ds}/cards").json() if c["kind"] == "widget"}
    widgets = {w["id"]: w for w in client.get(f"{API}/datasets/{ds}/widgets").json()["widgets"]}
    fare = {wid for wid, w in widgets.items() if w["spec"]["op"]["type"] == "sql" and "fare" in w["spec"]["op"]["sql"]}
    ml = {wid for wid, w in widgets.items() if w["spec"]["op"]["type"] == "ml"}  # its run reads fare: outdated, card too
    narrated = len(db_rows("SELECT 1 FROM llm_calls WHERE dataset_id = ? AND purpose = 'narrate'", ds))
    v = client.get(f"{API}/datasets/{ds}").json()["current_version"]
    client.post(f"{API}/datasets/{ds}/edits", json={"base_version": v, "edits": [{"row_id": 1, "column": "fare", "value": "500"}]})
    done = wait_for(lambda: next((j for j in client.get(f"{API}/jobs?dataset_id={ds}").json()
                                  if j["kind"] == "cascade" and j["status"] in ("done", "failed")), None), timeout=60)
    assert done["status"] == "done" and done["result"]["outdated"] == len(fare) + len(ml) and done["result"]["cards"] == 0, done
    after = {c["widget_id"]: c for c in client.get(f"{API}/datasets/{ds}/cards").json() if c["kind"] == "widget"}
    for wid in fare | ml:
        assert after[wid]["status"] == "outdated" and after[wid]["body"] == before[wid]["body"], widgets[wid]["title"]
    assert all(after[wid]["status"] == "ready" for wid in after if wid not in fare and widgets[wid]["spec"]["op"]["type"] == "sql")
    assert len(db_rows("SELECT 1 FROM llm_calls WHERE dataset_id = ? AND purpose = 'narrate'", ds)) == narrated


def test_the_words_around_a_chip_must_say_what_its_fact_is():
    """Day 7 review F4: live run cards read "influenced by 1.00", "importance is 0.373 lower than
    that of unit_price" (0.373 is units' own importance) and "Sex sex is the strongest driver"."""
    facts = {"driver_1": fx.fact("unit_price", "text", "factor number 1 by permutation importance"),
             "driver_1_importance": fx.fact(1.0, "num", "relative importance of unit_price (1 is the strongest)"),
             "driver_2": fx.fact("units", "text", "factor number 2 by permutation importance"),
             "driver_2_importance": fx.fact(0.373, "num", "relative importance of units (1 is the strongest)"),
             "model_score": fx.fact(0.804, "pct", "the model's accuracy on held-out rows"),
             "lift": fx.fact(2.4, "num", "points better than the best simple rule")}
    cols = ["unit_price", "units", "revenue", "sex"]

    def ok(runs):
        nr.to_runs(runs, facts, cols)

    ok([ChipRun(chip="driver_1"), TextRun(text=" is the strongest factor ("), ChipRun(chip="driver_1_importance"),
        TextRun(text="), then "), ChipRun(chip="driver_2"), TextRun(text=" ("), ChipRun(chip="driver_2_importance"), TextRun(text=").")])
    ok([LabelRun(label="column:units"), TextRun(text=" follows, at "), ChipRun(chip="driver_2_importance"), TextRun(text=".")])
    ok([TextRun(text="The model beats the simple rule by "), ChipRun(chip="lift"), TextRun(text=" points better than it.")])
    ok([TextRun(text="It shows units for each sex."), LabelRun(label="column:sex"), TextRun(text=" leads.")])  # a new sentence
    for bad, error in [
        ([TextRun(text="Revenue is most strongly linked with "), ChipRun(chip="driver_1_importance"), TextRun(text=".")], "importance of unit_price"),
        ([LabelRun(label="column:units"), TextRun(text=" matters less: its importance is "), ChipRun(chip="driver_2_importance"),
          TextRun(text=" lower than that of "), LabelRun(label="column:unit_price"), TextRun(text=".")], "not a difference"),
        ([TextRun(text="The strongest factors are "), ChipRun(chip="driver_1"), TextRun(text=" and "), ChipRun(chip="driver_2"),
          TextRun(text=", at "), ChipRun(chip="driver_1_importance"), TextRun(text=".")], "importance of unit_price"),
        ([TextRun(text="Sex "), LabelRun(label="column:sex"), TextRun(text=" is the strongest.")], "said twice"),
        ([TextRun(text="Unit_price "), ChipRun(chip="driver_1"), TextRun(text=" comes first.")], "said twice"),
        ([TextRun(text="Accuracy was "), ChipRun(chip="model_score"), TextRun(text=" higher than the rule.")], "not a difference"),
    ]:
        with pytest.raises(ValueError, match=error):
            ok(bad)


def test_a_synthesis_states_only_what_its_cards_say():
    """Day 8 review F1: a live synthesis joined true chips into a false number ("This shows an average
    unit price of 21.41") and drew a conclusion no card backs ("all point to Gizmo outperforming
    Sprocket"). Numbers from two cards are compared only when code can check the comparison."""
    from sherlock.stories import synthesis

    facts = {"c1.total": fx.fact(1025982.0, "num", "total revenue"), "c2.total": fx.fact(47715, "int", "total units"),
             "c3.price": fx.fact(21.41, "num", "average unit price"),
             "c1.rate": fx.fact(0.727, "pct", "rate for the top sex"), "c2.rate": fx.fact(0.382, "pct", "overall survival rate"),
             "c2.top_value": fx.fact(0.62, "pct", "rate for the top class"), "c2.bottom_value": fx.fact(0.24, "pct", "rate for the bottom class")}
    cols = ["revenue", "units", "unit_price", "product", "sex"]

    def check(runs):
        synthesis._check([runs], facts, cols, {"value:product:Gizmo", "value:product:Sprocket"})

    check([TextRun(text="Total revenue was "), ChipRun(chip="c1.total"), TextRun(text=" while total units were "), ChipRun(chip="c2.total"),
           TextRun(text=".")])
    check([TextRun(text="The top sex survived at "), ChipRun(chip="c1.rate"), TextRun(text=", higher than the overall "),
           ChipRun(chip="c2.rate"), TextRun(text=".")])
    check([TextRun(text="Within classes, survival ran from "), ChipRun(chip="c2.top_value"), TextRun(text=" down to "),
           ChipRun(chip="c2.bottom_value"), TextRun(text=", lower for the bottom class.")])  # one card's own numbers
    for bad, error in [
        ([TextRun(text="Revenue and units are both large. This shows an average unit price of "), ChipRun(chip="c3.price"),
          TextRun(text=".")], "conclusion"),
        ([TextRun(text="Returns and prices all point to "), LabelRun(label="value:product:Gizmo"), TextRun(text=" leading "),
          LabelRun(label="value:product:Sprocket"), TextRun(text=".")], "conclusion"),
        ([TextRun(text="The overall rate of "), ChipRun(chip="c2.rate"), TextRun(text=" is higher than the top sex's "),
          ChipRun(chip="c1.rate"), TextRun(text=".")], "wrong or unclear"),
        ([TextRun(text="Revenue of "), ChipRun(chip="c1.total"), TextRun(text=" is far above the "), ChipRun(chip="c2.rate"),
          TextRun(text=" survival rate.")], "hasn't compared"),
        ([TextRun(text="The top sex's "), ChipRun(chip="c1.rate"), TextRun(text=" is higher than "), ChipRun(chip="c2.top_value"),
          TextRun(text=" and "), ChipRun(chip="c2.bottom_value"), TextRun(text=".")], "hasn't compared"),
    ]:
        with pytest.raises(ValueError, match=error):
            check(bad)


def test_a_synthesis_takes_only_the_value_labels_its_cards_use():
    """Rule 2 (Day 6 review): synthesis and `ask_story` ran the narrator's checks without the allowed
    labels, so any `value:` label was shown as written."""
    from sherlock.stories import synthesis

    facts = {"c1.top_value": {"value": 0.7, "formatted": "70.0%", "label": "rate"}}
    values = synthesis._values(["column:sex", "value:sex:female"])
    ok = [TextRun(text="Survival was highest for "), LabelRun(label="value:sex:female"), TextRun(text=" passengers, at "),
          ChipRun(chip="c1.top_value")]
    synthesis._check([ok], facts, ["sex", "fare"], values)
    for bad in ([TextRun(text="Passengers paid about "), LabelRun(label="value:fare:512.33"), TextRun(text=" while survival was "),
                 ChipRun(chip="c1.top_value")],
                [TextRun(text="Over XLV passengers survived, at "), ChipRun(chip="c1.top_value")]):
        with pytest.raises(ValueError):
            synthesis._check([bad], facts, ["sex", "fare"], values)


# --- the update path: one job per dataset, write guards, failure hooks (plan 1.1, 1.2) -------------

def _settled(client, ds, timeout=120):
    """Every job of the dataset has finished (a cascade's re-runs and their stories too)."""
    return wait_for(lambda: (js := client.get(f"{API}/jobs?dataset_id={ds}").json())
                    and all(j["status"] in ("done", "failed", "cancelled") for j in js) and js, timeout=timeout)


def _edit(client, ds, column, value, row=1) -> int:
    v = client.get(f"{API}/datasets/{ds}").json()["current_version"]
    r = client.post(f"{API}/datasets/{ds}/edits", json={"base_version": v, "edits": [{"row_id": row, "column": column,
                                                                                       "value": value}]})
    assert r.status_code == 201, r.text
    return r.json()["version"]


def _fare_widgets(client, ds) -> set[str]:
    return {w["id"] for w in client.get(f"{API}/datasets/{ds}/widgets").json()["widgets"]
            if w["spec"]["op"]["type"] == "sql" and "fare" in w["spec"]["op"]["sql"]}


@pytest.mark.usefixtures("run_jobs")
def test_a_tell_that_a_newer_version_overtook_writes_nothing(mocked, client):
    """Plan 1.1: every card write is guarded by the version it was told on. A tell whose version is no
    longer the current one stores no text and no `ready`; its cards are left outdated for the newer
    version's cascade, and the overview isn't rewritten."""
    from sherlock.db.connection import connect
    from sherlock.llm.client import CallScope, LLMClient
    from sherlock.stories import service
    from sherlock.widgets import service as ws

    ds = _ready_with_stories(client)
    before = {c["id"]: c for c in client.get(f"{API}/datasets/{ds}/cards").json()}
    settings = client.app.state.settings
    db = connect(settings)
    try:
        old = db.execute("SELECT * FROM datasets WHERE id = ?", (ds,)).fetchone()
        db.execute("UPDATE datasets SET current_version = current_version + 1 WHERE id = ?", (ds,))  # a newer version
        out = service.tell(ws.Env(settings, db, client.app.state.duckdb, None), LLMClient(settings),
                           CallScope(user_id=old["user_id"], dataset_id=ds), old, None, reason="refresh")
        after = {r["id"]: r for r in db.execute("SELECT * FROM cards WHERE dataset_id = ?", (ds,)).fetchall()}
        db.execute("UPDATE datasets SET current_version = ? WHERE id = ?", (old["current_version"], ds))
    finally:
        db.close()
    assert out["cards"] == 0 and out["overtaken"]
    assert set(out["overtaken"]) <= {c["widget_id"] for c in before.values() if c["kind"] == "widget"}
    for cid, c in before.items():
        r = after[cid]
        assert json.loads(r["headline_json"]) == c["headline"] and json.loads(r["body_json"]) == c["body"], c["kind"]
        assert r["version"] == c["version"] and r["fact_sheet_id"] == c["fact_sheet_id"]
        assert r["status"] == ("outdated" if c["widget_id"] in out["overtaken"] else c["status"]), c["kind"]


@pytest.mark.usefixtures("run_jobs")
def test_a_cancelled_cascade_leaves_no_card_updating_and_the_next_one_tells_them(mocked, client, monkeypatch):
    """Plan 1.2: Cancel while the cards are being told leaves them outdated (Refresh), not spinning, and
    the widgets' versions don't move, so the next cascade tells them again."""
    from sherlock.db.connection import connect

    ds = _ready_with_stories(client)
    fare = _fare_widgets(client, ds)
    real = nr.narrate

    def cancel_then_narrate(*args, **kwargs):  # the user presses Cancel while the cards are being told
        db = connect(client.app.state.settings)
        try:
            db.execute("UPDATE jobs SET cancel_requested = 1 WHERE dataset_id = ? AND kind = 'cascade' AND status = 'running'",
                       (ds,))
        finally:
            db.close()
        return real(*args, **kwargs)

    monkeypatch.setattr(nr, "narrate", cancel_then_narrate)
    first = _edit(client, ds, "fare", "500")
    _settled(client, ds)
    cascades = [j for j in client.get(f"{API}/jobs?dataset_id={ds}").json() if j["kind"] == "cascade"]
    assert [j["status"] for j in cascades] == ["cancelled"], cascades
    cards = client.get(f"{API}/datasets/{ds}/cards").json()
    assert not [c for c in cards if c["status"] == "updating"]
    by_widget = {c["widget_id"]: c for c in cards if c["kind"] == "widget"}
    # A card told before Cancel took effect is ready on the new version; the rest offer Refresh.
    assert all(by_widget[w]["status"] == "outdated" or (by_widget[w]["status"] == "ready" and by_widget[w]["version"] == first)
               for w in fare)
    assert any(by_widget[w]["status"] == "outdated" for w in fare)
    built = {w["id"]: w["version_built"] for w in client.get(f"{API}/datasets/{ds}/widgets").json()["widgets"]}
    assert all(built[w] < first for w in fare)

    monkeypatch.setattr(nr, "narrate", real)
    second = _edit(client, ds, "age", "30", row=2)  # the next cascade reaches back to the cancelled one's change
    _settled(client, ds)
    cascades = [j for j in client.get(f"{API}/jobs?dataset_id={ds}").json() if j["kind"] == "cascade"]
    assert sorted(j["status"] for j in cascades) == ["cancelled", "done"]
    by_widget = {c["widget_id"]: c for c in client.get(f"{API}/datasets/{ds}/cards").json() if c["kind"] == "widget"}
    assert all(by_widget[w]["status"] == "ready" and by_widget[w]["version"] == second for w in fare)
    built = {w["id"]: w["version_built"] for w in client.get(f"{API}/datasets/{ds}/widgets").json()["widgets"]}
    assert all(built[w] == second for w in fare)


@pytest.mark.usefixtures("run_jobs")
def test_a_widget_the_user_changes_during_a_cascade_keeps_the_change(mocked, client, monkeypatch):
    """Plan 1.1: the cascade's widget writes are guarded by the `updated_at` it read. A user's change that
    lands between its read and its write wins: the old query's error isn't stamped over it."""
    from sherlock.db.connection import connect
    from sherlock.errors import ApiError
    from sherlock.widgets import service as ws

    ds = _ready_with_stories(client)
    fare = _fare_widgets(client, ds)
    target = next(w for w in client.get(f"{API}/datasets/{ds}/widgets").json()["widgets"] if w["id"] in fare)
    settings, real, raced = client.app.state.settings, ws.data, []

    def racing(env, dataset, row, *args, **kwargs):
        if row["id"] == target["id"] and not raced:
            raced.append(True)  # the user saves a change to this widget now, and the old query fails on the new version
            db = connect(settings)
            try:
                fresh = db.execute("SELECT * FROM datasets WHERE id = ?", (ds,)).fetchone()
                ws.update(ws.Env(settings, db, env.cache, None), fresh, ws.get_row(db, target["id"]), target["spec"],
                          "My own chart")
            finally:
                db.close()
            raise ApiError(422, "invalid", "the old query fails on the new version")
        return real(env, dataset, row, *args, **kwargs)

    monkeypatch.setattr(ws, "data", racing)
    _edit(client, ds, "fare", "500")
    _settled(client, ds)
    assert raced
    after = next(w for w in client.get(f"{API}/datasets/{ds}/widgets").json()["widgets"] if w["id"] == target["id"])
    assert after["title"] == "My own chart" and after["status"] == "ready" and after["error"] is None


@pytest.mark.usefixtures("run_jobs")
def test_a_failed_rerun_leaves_its_card_outdated(mocked, client, monkeypatch):
    """Plan 1.2: an analysis card says `updating` while its run re-runs and `outdated` when the run fails,
    never `ready` with the old run's story, and never spinning."""
    from sherlock.jobs.runner import HANDLERS, JobKind

    ds = _ready_with_stories(client)
    client.put(f"{API}/me/settings", json={"story_updates": "ask"})  # the cascade outdates the run without re-running it
    widget = next(w for w in client.get(f"{API}/datasets/{ds}/widgets").json()["widgets"] if w["spec"]["op"]["type"] == "ml")
    _edit(client, ds, "fare", "500")  # the analysis reads fare
    _settled(client, ds)

    async def broken(ctx):
        raise RuntimeError("the fit failed")

    monkeypatch.setitem(HANDLERS, "ml_run", JobKind(broken, HANDLERS["ml_run"].on_failure))
    run = client.post(f"{API}/widgets/{widget['id']}/rerun").json()
    _settled(client, ds)
    assert client.get(f"{API}/runs/{run['id']}").json()["status"] == "failed"
    card = next(c for c in client.get(f"{API}/datasets/{ds}/cards").json() if c["widget_id"] == widget["id"])
    assert card["status"] == "outdated"
    events = (json.loads(r["data_json"]) for r in db_rows(
        "SELECT data_json FROM job_events WHERE dataset_id = ? AND type = 'card.updated' ORDER BY id", ds))
    told = [d["status"] for d in events if d["id"] == card["id"]]
    assert told[-2:] == ["updating", "outdated"]


# --- the trustworthy-source rule (plan 1.3) -------------------------------------------------------

@pytest.mark.usefixtures("run_jobs")
def test_only_usable_cards_feed_another_output(mocked, client):
    """Plan 1.3: a card that is outdated, or told on a version whose numbers no longer hold, feeds no
    overview, synthesis or answer; the overview and the syntheses citing such cards are outdated too,
    the cascade's audit finds nothing left to fix, and the notebook says which cards aren't current."""
    from sherlock.db.connection import connect
    from sherlock.errors import ApiError
    from sherlock.jobs.purge import purge
    from sherlock.llm.client import CallScope, LLMClient
    from sherlock.notebook import exporter
    from sherlock.stories import service, synthesis, trust

    ds = _ready_with_stories(client)
    fare = _fare_widgets(client, ds)
    widgets = {w["id"]: w for w in client.get(f"{API}/datasets/{ds}/widgets").json()["widgets"]}
    ml = {wid for wid, w in widgets.items() if w["spec"]["op"]["type"] == "ml"}
    cards = {c["widget_id"] or "overview": c for c in client.get(f"{API}/datasets/{ds}/cards").json()}
    others = [cards[w]["id"] for w in cards if w not in fare | ml | {"overview"}]
    fare_card = cards[sorted(fare)[0]]["id"]
    settings = client.app.state.settings
    db = connect(settings)
    try:
        dataset = db.execute("SELECT * FROM datasets WHERE id = ?", (ds,)).fetchone()
        scope = CallScope(user_id=dataset["user_id"], dataset_id=ds)
        syn = synthesis.create(db, None, LLMClient(settings), scope, dataset, [fare_card, *others[:2]], list(dataset_columns(client, ds)))
    finally:
        db.close()

    client.put(f"{API}/me/settings", json={"story_updates": "ask"})
    _edit(client, ds, "fare", "500")
    jobs = _settled(client, ds)
    cascade = next(j for j in jobs if j["kind"] == "cascade")
    assert cascade["status"] == "done" and cascade["result"]["audited"] == 0, cascade
    after = {c["id"]: c for c in client.get(f"{API}/datasets/{ds}/cards").json()}
    assert after[cards["overview"]["id"]]["status"] == "outdated"
    cites_fare = fare_card in {k.partition(".")[0] for k in synthesis.chip_keys(syn)}
    assert after[syn["id"]]["status"] == ("outdated" if cites_fare else "ready")  # its fare card went outdated
    assert all(after[cards[w]["id"]]["status"] == "outdated" for w in fare | ml)

    db = connect(settings)
    try:
        dataset = db.execute("SELECT * FROM datasets WHERE id = ?", (ds,)).fetchone()
        assert trust.audit(db, None, dataset) == 0
        usable = {r["id"] for r in trust.usable_cards(db, dataset)}
        # Only the cards that read no fare stay usable, and the synthesis when it doesn't cite the fare card.
        assert usable == set(others) | (set() if cites_fare else {syn["id"]})
        left: list[str] = []
        cited = synthesis.sources(db, ds, [fare_card, *others[:2]], left)
        assert [r["id"] for r, _ in cited] == others[:2]
        assert len(left) == 1 and left[0].endswith("(outdated)") and "I left out" in synthesis.left_out_note(left)
        with pytest.raises(ApiError, match="I left out"):
            synthesis.create(db, None, LLMClient(settings), CallScope(), dataset, [fare_card, others[0]], ["fare"])
        # The notebook notes every card that isn't current, in italics under its heading.
        built = exporter.build(settings, db, client.app.state.duckdb, dataset, exporter.NotebookOptions())
        md = [c.source for c in built.nb.cells if c.cell_type == "markdown"]
        not_ready = [c for c in after.values() if c["status"] != "ready"]
        assert sum("*Out of date (outdated)" in m for m in md) == len(not_ready)
    finally:
        db.close()

    # Refreshing the overview reads only the usable cards; an analysis card on an outdated run stays outdated.
    for cid in (cards["overview"]["id"], cards[next(iter(ml))]["id"]):
        client.post(f"{API}/cards/{cid}/refresh")
    _settled(client, ds)
    overview = client.get(f"{API}/cards/{cards['overview']['id']}").json()
    assert overview["status"] == "ready"
    assert client.get(f"{API}/cards/{cards[next(iter(ml))]['id']}").json()["status"] == "outdated"
    db = connect(settings)
    try:
        sheet = service.get_sheet(db, overview["fact_sheet_id"])
        read = set().union(*(service.get_sheet(db, after[c]["fact_sheet_id"])["depends_columns"] for c in others))
        assert set(sheet["depends_columns"]) <= read and "fare" not in sheet["depends_columns"]

        # A purged widget's card can't be cited any more: the synthesis citing it says its sources changed.
        db.execute("UPDATE cards SET status = 'ready' WHERE id = ?", (syn["id"],))
        db.execute("UPDATE widgets SET deleted_at = '2000-01-01T00:00:00.000Z' WHERE id = ?", (cards[sorted(fare)[0]]["widget_id"],))
        purge(settings, db, None)
        assert service.fact_for(db, ds, f"{fare_card}.n") is None
        assert db.execute("SELECT status FROM cards WHERE id = ?", (syn["id"],)).fetchone()[0] == (
            "sources_changed" if cites_fare else "ready")
    finally:
        db.close()


def dataset_columns(client, ds) -> list[str]:
    return [c["name"] for c in client.get(f"{API}/datasets/{ds}/datacard").json()["columns"]]


@pytest.mark.usefixtures("run_jobs")
def test_switching_to_automatic_brings_outdated_cards_and_runs_up_to_date(mocked, client):
    """Plan 2b.3 (A19): under "Ask first" an edit leaves cards and the analysis's run outdated. Switching to
    "Automatic" queues a cascade that tells those cards again and re-runs the analysis, without a new
    edit; before, an already-outdated run was never picked up again."""
    ds = _ready_with_stories(client)
    ml = next(w for w in client.get(f"{API}/datasets/{ds}/widgets").json()["widgets"] if w["spec"]["op"]["type"] == "ml")
    client.put(f"{API}/me/settings", json={"story_updates": "ask"})
    _edit(client, ds, "fare", "500")
    _settled(client, ds)
    assert any(c["status"] == "outdated" for c in client.get(f"{API}/datasets/{ds}/cards").json())
    assert client.get(f"{API}/runs/{ml['run_id']}").json()["status"] == "outdated"

    client.put(f"{API}/me/settings", json={"story_updates": "auto"})
    jobs = _settled(client, ds, timeout=180)
    settings = [j for j in jobs if j["kind"] == "cascade" and j["status"] == "done"]
    assert len(settings) == 2, [j["kind"] for j in jobs]  # the edit's, then the switch's
    cards = client.get(f"{API}/datasets/{ds}/cards").json()
    assert [c for c in cards if c["status"] != "ready"] == []
    rerun = next(w for w in client.get(f"{API}/datasets/{ds}/widgets").json()["widgets"] if w["id"] == ml["id"])
    assert rerun["run_id"] != ml["run_id"]
    assert client.get(f"{API}/runs/{rerun['run_id']}").json()["status"] == "done"


@pytest.mark.usefixtures("run_jobs")
def test_under_automatic_a_synthesis_is_written_again_and_a_deleted_widgets_run_leaves_the_notebook(mocked, client):
    """Plan 2b.6 (A15): under "Automatic" a synthesis whose cited numbers moved is written again by a
    stories job after the cascade, with the changed badge, instead of waiting on Refresh. (A33) A deleted
    widget's run isn't exported as an extra run."""
    from sherlock.db.connection import connect
    from sherlock.llm.client import CallScope, LLMClient
    from sherlock.notebook import exporter
    from sherlock.stories import synthesis

    ds = _ready_with_stories(client)
    cards = [c for c in client.get(f"{API}/datasets/{ds}/cards").json() if c["kind"] == "widget"]
    settings = client.app.state.settings
    db = connect(settings)
    try:
        dataset = db.execute("SELECT * FROM datasets WHERE id = ?", (ds,)).fetchone()
        syn = synthesis.create(db, None, LLMClient(settings), CallScope(), dataset, [c["id"] for c in cards[:3]],
                               dataset_columns(client, ds))
        # One cited number as it was before the edit, so the cascade's check finds it moved.
        body = json.loads(db.execute("SELECT body_json FROM cards WHERE id = ?", (syn["id"],)).fetchone()[0])
        chip = next(r for b in body["blocks"] for r in b["runs"] if r["type"] == "chip")
        chip["value"] = "-1"
        db.execute("UPDATE cards SET body_json = ? WHERE id = ?", (json.dumps(body), syn["id"]))
    finally:
        db.close()
    _edit(client, ds, "fare", "500")
    jobs = _settled(client, ds)
    rewrites = [j for j in jobs if j["kind"] == "stories" and j["result"] and j["result"].get("widgets") == 0]
    assert rewrites and rewrites[0]["status"] == "done", [(j["kind"], j["status"], j["result"]) for j in jobs]
    after = client.get(f"{API}/cards/{syn['id']}").json()
    assert after["status"] == "ready" and after["changed_badge"]
    assert all(r["value"] != "-1" for b in after["body"]["blocks"] for r in b["runs"] if r["type"] == "chip")

    ml = next(w for w in client.get(f"{API}/datasets/{ds}/widgets").json()["widgets"] if w["spec"]["op"]["type"] == "ml")
    assert client.delete(f"{API}/widgets/{ml['id']}").status_code == 204
    db = connect(settings)
    try:
        live = exporter._widgets(db, ds)
        assert ml["run_id"] not in [r["id"] for r in exporter._extra_runs(db, ds, live)]
    finally:
        db.close()
