"""Grounding (docs/plans/tavily.md §3.2): Tavily finds the file's data dictionary and explains cryptic column
names at the start of the review job. Every test runs on recorded replies (`tests/fixtures/ground_*.json`):
none reaches Tavily or a model."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sherlock.agent import web as aw
from sherlock.cleaning import ground as gr
from sherlock.config import get_settings
from sherlock.db.connection import connect
from sherlock.db.migrate import migrate
from sherlock.llm.client import CallScope, LLMClient
from sherlock.main import create_app
from sherlock.llm.fixtures import FixtureTransport
from sherlock.web.client import WebClient
from sherlock.web.fixtures import FailingTransport, WebFixtureTransport

FIXTURES = Path(__file__).parent / "fixtures"
COLUMNS = ["Pclass", "SibSp", "Parch", "Name"]
CELLS = {"Pclass": [3, 1], "SibSp": [1, 0], "Parch": [0, 2], "Name": ["Braund Owen", "Heikkinen Laina"]}
CARD = {"columns": [
    {"name": "Pclass", "type": "int", "top_values": [{"value": 3}, {"value": 1}]},
    {"name": "SibSp", "type": "int", "top_values": [{"value": 1}, {"value": 0}]},
    {"name": "Parch", "type": "int", "top_values": [{"value": 0}, {"value": 2}]},
    {"name": "Name", "type": "text", "sample_values": ["Braund Owen", "Heikkinen Laina"]}]}
LONG_AGO = "2020-01-01T00:00:00.000Z"


@pytest.fixture
def db():
    c = connect(get_settings())
    migrate(c)
    c.execute("INSERT INTO users (id, cookie_token, created_at, last_seen_at) VALUES ('u1', 'h', 'x', 'x')")
    c.execute("INSERT INTO datasets (id, user_id, name, original_filename, status, import_options_json, expires_at, created_at) "
              "VALUES ('ds_g', 'u1', 'x', 'x.csv', 'ready', '{}', 'x', 'x')")
    seed_version(c, COLUMNS)
    # The category column's values are in the value index, as the profile leaves them.
    c.execute("INSERT INTO value_index (dataset_id, column, value, count, version) VALUES ('ds_g', 'Name', 'Braund Owen', 1, 1)")
    yield c
    c.close()


def seed_version(db, columns, version=1):
    db.execute("INSERT INTO versions (dataset_id, version, parquet_path, row_count, column_count, columns_json, created_at) "
               "VALUES ('ds_g', ?, 'v.parquet', 2, ?, ?, ?)",
               (version, len(columns), json.dumps([{"name": c, "type": "text"} for c in columns]), LONG_AGO))


def dataset(db):
    return db.execute("SELECT * FROM datasets WHERE id = 'ds_g'").fetchone()


def llm():
    return LLMClient(get_settings(), transport=FixtureTransport.load(FIXTURES / "ground_llm.json"))


def web_transport():
    return WebFixtureTransport.load(FIXTURES / "ground_web.json")


def run(db, fake, card=CARD, **kw):
    scope = CallScope(user_id="u1", dataset_id="ds_g")
    return gr.ground(get_settings(), db, dataset(db), card, scope, llm=kw.pop("llm", None) or llm(),
                     web=WebClient(get_settings(), fake), **kw)


def web_rows(db):
    return [dict(r) for r in db.execute("SELECT * FROM llm_calls WHERE role = 'web' ORDER BY id")]


# --- what grounding does -----------------------------------------------------------------------

def test_grounding_stores_found_notes_and_returns_the_excerpts(db):
    fake = web_transport()
    got = run(db, fake)
    # The dictionary page's three excerpts, then the quote the cryptic column's web note was written from.
    assert [e["n"] for e in got] == [1, 2, 3, 4]
    assert got[0]["url"] == "https://codebook.example.org/passengers" and got[0]["text"].startswith("Pclass: the passenger class")
    assert got[3]["url"] == "https://glossary.example.org/parch" and got[3]["text"].startswith("Parch is the number")
    assert {"n", "url", "title", "text", "retrieved_at"} == set(got[0])
    notes = {n["column"]: n for n in aw.notes_for(db, "ds_g")}
    assert {c: n["kind"] for c, n in notes.items()} == {"Pclass": "found", "SibSp": "found", "Parch": "web"}
    assert "1 = first" in notes["Pclass"]["excerpt"] and notes["Pclass"]["source_url"] == "https://codebook.example.org/passengers"
    assert notes["Parch"]["source_url"] == "https://glossary.example.org/parch"
    # The search, one read of the top result, and one search for the cryptic column left: three calls.
    assert [c["kind"] for c in fake.calls] == ["search", "extract", "search"]
    assert [r["purpose"] for r in web_rows(db)] == ["ground_search", "dictionary", "ground_meaning"]
    first = fake.calls[0]["params"]
    assert first["query"] == "dataset columns Pclass SibSp Parch Name column descriptions"
    assert first["include_answer"] is False and all("include_answer" not in c["params"] or c["params"]["include_answer"] is False
                                                    for c in fake.calls)
    assert fake.calls[1]["params"]["urls"] == ["https://codebook.example.org/passengers"]  # the noisy result isn't read


def test_notes_come_in_order_and_are_labelled(db):
    for kind in ("web", "found", "dictionary"):
        aw.save_note(db, "ds_g", "Pclass", kind, f"A {kind} note.", None, "https://e.org/p", "P", "2026-10-28")
    assert [n["kind"] for n in aw.notes_for(db, "ds_g")] == ["dictionary", "found", "web"]
    assert [n["kind"] for n in aw.notes_for(db, "ds_g", kinds=("found",))] == ["found"]
    assert aw.notes_context(db, "ds_g", ["Pclass"]).splitlines() == [
        "- Pclass: A dictionary note. (from a data dictionary)",
        "- Pclass: A found note. (from a data dictionary Sherlock found)",
        "- Pclass: A web note. (from the web)"]
    found = aw.notes_for(db, "ds_g", kinds=("found",))[0]
    assert "Sherlock found" in aw.note_block(found)["body"]["blocks"][0]["runs"][0]["text"]


def test_a_found_dictionary_is_an_allowed_note_kind(client, db):
    from sherlock.routers.datasets import ColumnNote

    ColumnNote(column="a", kind="found", description="d", excerpt=None, source_url="https://e.org", source_title=None,
               retrieved_at="2026-10-28")
    with pytest.raises(ValueError):
        ColumnNote(column="a", kind="invented", description="d", excerpt=None, source_url="https://e.org", source_title=None,
                   retrieved_at="2026-10-28")


def test_read_dictionary_keeps_the_kind_and_returns_the_excerpts(db):
    out = aw.read_dictionary(llm(), CallScope(user_id="u1"), WebClient(get_settings(), web_transport()), db, "ds_g",
                             "https://codebook.example.org/passengers", COLUMNS, kind="found")
    assert out["note"] is None and {n["kind"] for n in out["notes"]} == {"found"} and len(out["excerpts"]) == 3
    failed = aw.read_dictionary(llm(), CallScope(), WebClient(get_settings(), FailingTransport()), db, "ds_g",
                                "https://other.example.org/page", COLUMNS)
    assert failed["excerpts"] == [] and failed["notes"] == []


def test_column_meaning_saves_a_web_note_without_the_chat_toolkit(db):
    assert aw.column_meaning(llm(), CallScope(user_id="u1"), WebClient(get_settings(), web_transport()), db, "ds_g", "Parch",
                             COLUMNS, "column: Parch\ntype: int\nexamples: 0, 2") is True
    assert [(n["column"], n["kind"]) for n in aw.notes_for(db, "ds_g")] == [("Parch", "web")]
    assert aw.column_meaning(llm(), CallScope(), WebClient(get_settings(), FailingTransport()), db, "ds_g", "SibSp",
                             COLUMNS, "column: SibSp") is False


def test_notes_updated_goes_out_when_notes_were_stored(db):
    run(db, web_transport())
    events = [dict(r) for r in db.execute("SELECT * FROM job_events WHERE type = 'notes.updated'")]
    assert len(events) == 1 and json.loads(events[0]["data_json"]) == {"dataset_id": "ds_g"}
    # Nothing stored, no event.
    db.execute("DELETE FROM job_events")
    run(db, FailingTransport())
    assert db.execute("SELECT count(*) FROM job_events").fetchone()[0] == 0


# --- what goes out -----------------------------------------------------------------------------

def test_no_request_holds_a_cell_value_or_the_file_name(db):
    fake = web_transport()
    run(db, fake)
    sent = json.dumps([c["params"] for c in fake.calls], ensure_ascii=False).lower()
    for column, values in CELLS.items():
        for value in values:
            if isinstance(value, str):
                assert value.lower() not in sent, (column, value)
    for word in ("braund", "heikkinen", "x.csv"):
        assert word not in sent


def test_a_query_that_would_carry_a_file_value_is_not_sent(db):
    db.execute("INSERT INTO value_index (dataset_id, column, value, count, version) VALUES ('ds_g', 'Name', 'Column Descriptions', 1, 1)")
    fake = web_transport()
    assert run(db, fake) == [] and fake.calls == []


# --- fail soft ---------------------------------------------------------------------------------

def test_no_key_a_502_or_a_timeout_returns_nothing_and_raises_nothing(db):
    assert gr.ground(get_settings(), db, dataset(db), CARD, CallScope(user_id="u1"), llm=llm(), web=WebClient(get_settings())) == []
    assert web_rows(db) == []  # no key: nothing was even attempted
    for how in ("failed", "timeout"):
        fake = FailingTransport(how)
        assert run(db, fake) == []
        assert len(fake.calls) == 1  # the search failed, so nothing else was tried
    assert aw.notes_for(db, "ds_g") == []


def test_a_model_that_has_no_answer_leaves_what_was_read_and_raises_nothing(db):
    silent = LLMClient(get_settings(), transport=FixtureTransport([]))
    assert run(db, web_transport(), llm=silent) == []  # Super couldn't map the page, and the cryptic columns got no sentence
    assert aw.notes_for(db, "ds_g") == []


def test_grounding_off_or_without_a_model_does_nothing(db, monkeypatch):
    fake = web_transport()
    monkeypatch.setenv("CLEAN_GROUND", "off")
    get_settings.cache_clear()
    assert run(db, fake) == [] and fake.calls == []
    monkeypatch.setenv("CLEAN_GROUND", "on")
    get_settings.cache_clear()
    no_model = gr.ground(get_settings(), db, dataset(db), CARD, CallScope(user_id="u1"), web=WebClient(get_settings(), fake))
    assert no_model == [] and fake.calls == []  # no injected model, no LLM_BASE_URL, no recorded replies


# --- budget and once-per-dataset ---------------------------------------------------------------

def use_calls(db, n, user="u1"):
    for _ in range(n):
        db.execute("INSERT INTO llm_calls (user_id, role, model, purpose, ok, created_at, cached) "
                   "VALUES (?, 'web', 'tavily-search', 'web_context', 1, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), 0)", (user,))


def test_calls_left_counts_this_hours_uncached_calls(db, monkeypatch):
    web = WebClient(get_settings(), web_transport())
    assert web.calls_left(CallScope(user_id="u1")) == 20
    use_calls(db, 17)
    assert web.calls_left(CallScope(user_id="u1")) == 3
    use_calls(db, 5)
    assert web.calls_left(CallScope(user_id="u1")) == 0  # never negative
    assert web.calls_left(CallScope(user_id="u2")) == 20 and web.calls_left(CallScope()) is None  # no user, no cap
    monkeypatch.setenv("WEB_RATE_LIMIT", "0")
    get_settings.cache_clear()
    assert WebClient(get_settings(), web_transport()).calls_left(CallScope(user_id="u1")) is None


def test_with_fewer_than_five_calls_left_grounding_makes_no_call_and_chat_still_runs(db):
    use_calls(db, 17)
    fake = web_transport()
    assert run(db, fake) == [] and fake.calls == []
    # Chat's own search is still allowed with three left.
    WebClient(get_settings(), fake).search("fiscal year meaning", scope=CallScope(user_id="u1"), purpose="web_context")
    assert len(fake.calls) == 1


def test_a_second_run_on_the_same_dataset_makes_no_call(db):
    fake = web_transport()
    assert run(db, fake)
    made = len(fake.calls)
    assert run(db, fake) == [] and len(fake.calls) == made


def test_a_run_that_found_nothing_is_not_repeated(db):
    nothing = WebFixtureTransport([{"kind": "search", "match": [], "response": {"results": []}}])
    assert run(db, nothing) == []
    made = len(nothing.calls)
    assert made == 1 + 3  # the dictionary search, then one search for each of the three cryptic names
    assert run(db, nothing) == [] and len(nothing.calls) == made  # the search worked, so the dataset counts as grounded


def test_a_failed_search_is_tried_again_next_time(db):
    broken = FailingTransport()
    assert run(db, broken) == [] and len(broken.calls) == 1
    assert run(db, broken) == [] and len(broken.calls) == 2


def test_only_a_new_column_is_grounded_later(db):
    run(db, web_transport())
    fake = web_transport()
    card = {"columns": [*CARD["columns"], {"name": "ICD10", "type": "text", "sample_values": ["x"]}]}
    run(db, fake, card=card)
    assert fake.calls[0]["params"]["query"] == "dataset columns ICD10 column descriptions"
    assert {n["column"] for n in aw.notes_for(db, "ds_g")} >= {"Pclass", "SibSp", "Parch", "ICD10"}
    # ... and a version made later with the same columns grounds nothing.
    seed_version(db, [*COLUMNS, "ICD10"], version=2)
    db.execute("UPDATE versions SET created_at = ? WHERE version = 2", (LONG_AGO.replace("2020", "2021"),))
    again = web_transport()
    assert run(db, again, card=card) == [] and again.calls == []


def test_a_dictionary_the_user_linked_is_enough(db):
    aw.save_note(db, "ds_g", "Pclass", "dictionary", "The class.", "Pclass: the class", "https://e.org/d", "D", "2026-10-28")
    fake = web_transport()
    assert run(db, fake) == [] and fake.calls == []


def test_a_run_makes_at_most_nine_calls(db):
    cols = ["Sib", "Pcls", "Prch", "Tkt", "Cbn", "Emb", "Name"]
    card = {"columns": [{"name": c, "type": "text"} for c in cols]}
    seed_columns = [c for c in cols]
    db.execute("DELETE FROM versions")
    seed_version(db, seed_columns)
    db.execute("UPDATE versions SET columns_json = '[]'")  # none known: all are new
    # A site root every time, so each read costs an extract, a map and a second extract.
    root = WebFixtureTransport([
        {"kind": "search", "match": ["column descriptions"], "response": {"results": [
            {"url": "https://a.example.org", "title": "A", "score": 0.9, "content": "c"},
            {"url": "https://b.example.org", "title": "B", "score": 0.9, "content": "c"}]}},
        {"kind": "extract", "match": [], "response": {"results": [{"url": "https://x.example.org", "raw_content": "short"}]}},
        {"kind": "map", "match": [], "response": {"results": ["https://a.example.org/p"]}},
        {"kind": "search", "match": ["meaning"], "response": {"results": []}}])
    run(db, root, card=card)
    kinds = [c["kind"] for c in root.calls]
    assert len(kinds) == gr.MAX_CALLS and kinds.count("search") == 1 + gr.MAX_CRYPTIC  # the reads stop at five, the rest are searches


# --- which names look like codes ---------------------------------------------------------------

@pytest.mark.parametrize("name,expected", [
    ("SibSp", True), ("Pclass", True), ("Parch", True), ("ICD10", True), ("cust_nm", True), ("SKU", True), ("qty", True),
    ("Name", False), ("age", False), ("date", False), ("price", False), ("customer_id", False), ("Fare", False),
    ("order_date", False), ("q1_sales", False), ("region", False), ("Revenue", False), ("Unnamed: 0", False), ("x", False)])
def test_which_names_look_like_codes(name, expected):
    assert gr.looks_like_code(name) is expected


def test_capitals_say_nothing_when_every_name_is_in_capitals():
    assert gr.cryptic(["NAME", "SALARY", "SKU"]) == []
    assert gr.cryptic(["Name", "Salary", "SKU"]) == ["SKU"]
    assert gr.cryptic(["Pclass", "SibSp", "Parch", "ICD10", "Name"], skip={"SibSp"}) == ["Pclass", "Parch", "ICD10"]
    assert len(gr.cryptic([f"c{i}x_{i}" for i in range(9)])) == gr.MAX_CRYPTIC


def test_the_search_query_is_trimmed_to_whole_names():
    names = [f"column_number_{i:03d}" for i in range(60)]
    q = gr.search_query(names)
    assert len(q) <= 400 and q.startswith(gr.PREFIX) and q.endswith(gr.SUFFIX)
    assert q.split(gr.SUFFIX)[0].split()[-1] in names


# --- the search's dates ------------------------------------------------------------------------

def test_search_sends_a_start_and_end_date_and_drops_an_invalid_one(db):
    fake = WebFixtureTransport([{"kind": "search", "match": [], "response": {"results": []}}])
    client = WebClient(get_settings(), fake)
    client.search("news a", scope=CallScope(), purpose="t", topic="news", start_date="2026-03-01", end_date="2026-03-31")
    client.search("news b", scope=CallScope(), purpose="t", start_date="2026-3-1", end_date="2026-02-30")
    client.search("news c", scope=CallScope(), purpose="t", start_date="last month", end_date="2026-03-31")
    a, b, c = (x["params"] for x in fake.calls)
    assert (a["start_date"], a["end_date"]) == ("2026-03-01", "2026-03-31") and a["include_answer"] is False
    assert "start_date" not in b and "end_date" not in b
    assert "start_date" not in c and c["end_date"] == "2026-03-31"


def test_tavilys_client_takes_the_dates():
    import inspect

    from tavily import TavilyClient

    assert {"start_date", "end_date"} <= set(inspect.signature(TavilyClient.search).parameters)


# --- /healthz ----------------------------------------------------------------------------------

def test_healthz_says_whether_the_web_is_on_and_nothing_more(client, monkeypatch):
    assert client.get("/healthz").json()["web"] == {"enabled": False}
    monkeypatch.setenv("WEB_MOCK", str(FIXTURES / "ground_web.json"))
    get_settings.cache_clear()
    with TestClient(create_app()) as on:
        assert on.get("/healthz").json()["web"] == {"enabled": True}


# --- the review job ----------------------------------------------------------------------------

@pytest.fixture
def grounded_env(run_jobs, monkeypatch):
    """The review on, grounding on recorded replies; rating and suggesting by the review tests' scripted model."""
    from sherlock.cleaning import review
    from tests.test_cleaning_review import ScriptedLLM

    monkeypatch.setenv("CLEAN_REVIEW", "on")
    monkeypatch.setenv("LLM_MOCK", str(FIXTURES / "ground_llm.json"))
    monkeypatch.setenv("WEB_MOCK", str(FIXTURES / "ground_web.json"))
    monkeypatch.setattr(review, "LLMClient", ScriptedLLM)
    ScriptedLLM.calls, ScriptedLLM.fail, ScriptedLLM.suggestions = [], set(), []
    get_settings.cache_clear()


def test_the_review_job_grounds_first_and_tells_the_page(grounded_env, client):
    from tests.test_cleaning_review import ScriptedLLM
    from tests.test_jobs import API, upload, wait_for, wait_status

    ds = upload(client, b"Pclass,SibSp,Parch,Name\n3,1,0,Braund Owen\n1,0,2,Heikkinen Laina\n")
    wait_status(client, ds["id"], "offer")
    wait_for(lambda: all(j["status"] == "done" for j in client.get(f"{API}/jobs", params={"dataset_id": ds["id"]}).json()
                         if j["kind"] == "review_issues") and ScriptedLLM.calls)
    notes = client.get(f"{API}/datasets/{ds['id']}/column-notes").json()["notes"]
    assert {n["column"]: n["kind"] for n in notes} == {"Pclass": "found", "SibSp": "found", "Parch": "web"}
    db = connect(get_settings())
    try:
        assert db.execute("SELECT count(*) FROM job_events WHERE dataset_id = ? AND type = 'notes.updated'", (ds["id"],)).fetchone()[0] == 1
        assert [r[0] for r in db.execute("SELECT purpose FROM llm_calls WHERE role = 'web' ORDER BY id")] == [
            "ground_search", "dictionary", "ground_meaning"]
    finally:
        db.close()
