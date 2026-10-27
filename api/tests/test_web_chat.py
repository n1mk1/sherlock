"""Chat with the web (TRD §8.2 `web_context` and `ask_meaning`, PRD ASK-11, LOAD-7): the whole message path
with recorded Nemotron replies and a capturing fake Tavily, so what would have gone out is checked."""

import json
from pathlib import Path

import pytest

from sherlock import ratelimit
from sherlock.config import get_settings
from sherlock.llm import fixtures
from sherlock.llm.text import has_digits
from sherlock.llm.wording import wording_problem
from sherlock.web import client as web_client
from sherlock.web.fixtures import FailingTransport, WebFixtureTransport
from tests.test_chat import send
from tests.test_jobs import wait_status

API = "/api/v1"
FIXTURE = Path(__file__).parent / "fixtures" / "llm" / "web_chat.json"
CSV = b"region,status_code,amount,street\n" + b"".join(
    f"{r},{s},{a},{st}\n".encode() for r, s, a, st in [("North", 1, 10, "Ashford Lane 12"), ("South", 2, 12, "Mill Road 3"),
                                                       ("North", 1, 7, "Ashford Lane 12"), ("East", 3, 30, "Mill Road 3")] * 5)
PAGE = {"title": "Glossary of shipping terms", "url": "https://glossary.example.org/status", "score": 0.9,
        "content": "A status code records where a parcel is; code 7 means returned to sender."}
TAVILY = [
    {"kind": "search", "match": ["couriers"], "response": {"results": [PAGE]}},
    {"kind": "search", "match": ["shipping status code"], "response": {"results": [PAGE, {**PAGE, "url": "https://low.example.org", "score": 0.1}]}},
    {"kind": "search", "match": ["fiscal year"], "response": {"results": [
        {"title": "Fiscal year", "url": "https://finance.example.org/fy", "score": 0.8, "content": "A fiscal year runs 12 months."}]}},
    {"kind": "search", "match": ['"status_code" meaning'], "response": {"results": [PAGE]}},
    {"kind": "extract", "match": [], "response": {"results": [{"url": "https://codebook.example.org/vars", "title": "Variables",
        "raw_content": "status_code: delivery status of the order, where 1 = shipped, 2 = returned and 3 = lost; " * 4}]}},
]
pytestmark = pytest.mark.usefixtures("run_jobs")


class Model(fixtures.FixtureTransport):
    pass


@pytest.fixture(autouse=True)
def model(monkeypatch):
    """One fixture transport for every request, so a test can read the prompts. Before the app is made, so
    its settings carry the fixture file."""
    shared = Model.load(FIXTURE)
    monkeypatch.setenv("LLM_MOCK", str(FIXTURE))
    monkeypatch.setattr(fixtures.FixtureTransport, "load", classmethod(lambda cls, path: shared))
    monkeypatch.setitem(ratelimit.LIMITS_PER_MINUTE, "llm", 100)
    get_settings.cache_clear()
    return shared


@pytest.fixture
def tavily(monkeypatch):
    """Web retrieval on, answered by a capturing fake: `tavily.calls` is everything that would have been sent."""
    fake = WebFixtureTransport(json.loads(json.dumps(TAVILY)))
    monkeypatch.setattr(web_client, "make_transport", lambda settings: fake)
    return fake


@pytest.fixture
def ds(client):
    d = client.post(f"{API}/datasets", files={"file": ("orders.csv", CSV, "text/csv")}).json()
    wait_status(client, d["id"], "offer")
    return d


def web_blocks(msg):
    return [b for b in msg["blocks"] if b.get("labeled") == "web"]


def model_text(block):
    return [r["text"] for p in block["body"]["blocks"] for r in p["runs"] if r["type"] == "text"][1:]  # after the lead


def test_an_outside_world_question_is_answered_from_the_web_with_citations(client, ds, tavily):
    events, msg = send(client, ds["id"], "what does a shipping status code usually mean in general?")
    assert ("status", {"text": "Searching the web"}) in events and not [e for e, _ in events if e == "error"]
    (web,) = web_blocks(msg)
    runs = web["body"]["blocks"][0]["runs"]
    assert runs[0]["text"].startswith("From the web (not from your data)")
    assert {"type": "cite", "n": 1, "url": PAGE["url"], "title": PAGE["title"]} in runs
    assert not any(r["type"] == "chip" for r in runs)  # web facts never become chips
    assert all(not has_digits(t) and wording_problem(t) is None for t in model_text(web))
    listing = next(b for b in msg["blocks"] if b["type"] == "web_sources")
    assert listing["query"] == "shipping status code meaning" and [r["url"] for r in listing["results"]] == [PAGE["url"]]
    assert "code 7" in listing["results"][0]["snippet"]  # the web's number stays inside its quote
    assert [s["kind"] for s in msg["sources"]] == ["web"] and msg["sources"][0]["url"] == PAGE["url"]
    sent = tavily.calls[0]["params"]
    assert sent["include_answer"] is False and sent["query"] == "shipping status code meaning"
    calls = client.get(f"{API}/chat/messages/{msg['id']}/calls").json()["calls"]
    assert [(c["role"], c["purpose"]) for c in calls] == [("small", "route"), ("medium", "web_query"),
                                                          ("web", "web_context"), ("medium", "web_answer")]
    assert calls[2]["results"] == 2 and calls[2]["model"] == "tavily-search"


def test_without_a_key_an_outside_world_question_gets_one_line(client, ds):
    events, msg = send(client, ds["id"], "what is a fiscal year in general?")
    assert not [e for e, _ in events if e == "error"]
    assert msg["text"] == web_client.NOTES["off"] and not web_blocks(msg) and msg["sources"] == []


def test_a_query_holding_a_cell_value_is_never_sent(client, ds, tavily):
    _, msg = send(client, ds["id"], "what is the history of this kind of order?")
    assert "values from your file" in msg["text"] and tavily.calls == []


def test_a_timeout_degrades_only_the_web_part(client, ds, monkeypatch):
    fake = FailingTransport("timeout")
    monkeypatch.setattr(web_client, "make_transport", lambda settings: fake)
    events, msg = send(client, ds["id"], "total amount by region, and what a fiscal year is in general")
    assert not [e for e, _ in events if e == "error"]
    assert any(b["type"] == "table" for b in msg["blocks"])  # the data step still answers
    assert web_client.NOTES["timeout"] in msg["text"] and not web_blocks(msg)


def test_data_and_web_steps_sit_side_by_side_and_are_never_compared(client, ds, tavily):
    _, msg = send(client, ds["id"], "total amount by region, and what a fiscal year is in general")
    assert any(b["type"] == "table" for b in msg["blocks"]) and web_blocks(msg)
    assert "I didn't compare it with the numbers above" in msg["text"]
    assert {s["kind"] for s in msg["sources"]} == {"sql", "web"}


def test_column_meaning_comes_from_the_web_and_is_kept_as_the_columns_note(client, ds, tavily, model):
    _, msg = send(client, ds["id"], "what does status_code mean?")
    (web,) = web_blocks(msg)
    assert web["body"]["blocks"][0]["runs"][0]["text"].startswith("In general, from the web")
    assert {s["kind"] for s in msg["sources"]} == {"sql", "web"} and "general" not in {s["kind"] for s in msg["sources"]}
    assert tavily.calls[0]["params"]["query"].startswith('"status_code" meaning')  # names only, never values
    notes = client.get(f"{API}/datasets/{ds['id']}/column-notes").json()["notes"]
    assert [(n["column"], n["kind"]) for n in notes] == [("status_code", "web")] and "code 7" in notes[0]["excerpt"]
    model.calls.clear()
    send(client, ds["id"], "what is a fiscal year in general?")
    route = next(c["prompt"] for c in model.calls if c["purpose"] == "route")
    assert "What some columns mean (from a data dictionary or the web, not from the data):\n<data>\n- status_code:" in route


def test_without_a_key_column_meaning_is_todays_answer(client, ds):
    _, msg = send(client, ds["id"], "what does status_code mean?")
    assert [s["kind"] for s in msg["sources"]] == ["sql", "sql", "general"]
    assert not web_blocks(msg) and not any(n in msg["text"] for n in web_client.NOTES.values())
    assert next(b for b in msg["blocks"] if b.get("labeled") == "general")


def test_a_failed_search_keeps_the_general_meaning_with_one_line(client, ds, monkeypatch):
    monkeypatch.setattr(web_client, "make_transport", lambda settings: FailingTransport("failed"))
    _, msg = send(client, ds["id"], "what does status_code mean?")
    assert web_client.NOTES["failed"] in msg["text"]
    assert [s["kind"] for s in msg["sources"]] == ["sql", "sql", "general"]


def test_use_the_codebook_at_a_url_reads_it_from_chat(client, ds, tavily):
    _, msg = send(client, ds["id"], "use the codebook at https://codebook.example.org/vars")
    assert "it describes status_code" in msg["text"] and msg["sources"][0]["url"] == "https://codebook.example.org/vars"
    assert tavily.calls[0]["kind"] == "extract" and tavily.calls[0]["params"]["urls"] == ["https://codebook.example.org/vars"]
    _, meaning = send(client, ds["id"], "what does status_code mean?")
    (web,) = web_blocks(meaning)
    assert web["body"]["blocks"][0]["runs"][0]["text"].startswith("From the data dictionary you linked")
    assert len(tavily.calls) == 1  # the user's own dictionary wins over a search


def test_the_web_key_is_never_exported(monkeypatch):
    import nbformat

    from sherlock.notebook import scan

    monkeypatch.setenv("TAVILY_API_KEY", "tvly-not-a-real-key-123")
    get_settings.cache_clear()
    assert "tvly-not-a-real-key-123" in scan._configured_secrets()  # a configured key is never exported
    with pytest.raises(scan.ScanError):
        scan.scan(nbformat.v4.new_notebook(cells=[nbformat.v4.new_markdown_cell("key: tvly-not-a-real-key-123")]))


@pytest.mark.parametrize("question,query", [
    ("what is a fiscal year, in plain words?", "fiscal year definition"),
    ("historically, what was a fiscal year?", "fiscal year definition"),
    ("how do couriers usually assign a status_code to a parcel?", "how couriers assign shipping status codes"),
])
def test_an_outside_world_question_routed_to_the_file_goes_to_the_web(client, ds, tavily, question, query):
    # Live, Nano sent "what is <a term>?" to ask_meaning (no column of the file named), "what did a <column word>
    # usually include?" to ask_meaning (no word asking a meaning) and "historically, …" to ask_history (no word about
    # changes); each goes to web_context in code.
    _, msg = send(client, ds["id"], question)
    assert web_blocks(msg) and tavily.calls[0]["params"]["query"] == query
