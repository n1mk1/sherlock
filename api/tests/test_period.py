"""Outside context next to a dated answer (docs/plans/tavily.md §3.6): the jump is found in code, the button
carries a period code made, and pressing it runs one dated news search with no value of the file in it."""

import datetime as dt
import json
from pathlib import Path

import pytest

from sherlock import ratelimit
from sherlock.agent import period
from sherlock.agent.answerers import Result
from sherlock.config import get_settings
from sherlock.llm import fixtures
from sherlock.llm.text import has_digits
from sherlock.llm.wording import wording_problem
from sherlock.web import client as web_client
from sherlock.web.fixtures import FailingTransport, WebFixtureTransport
from tests.test_chat import send
from tests.test_jobs import wait_status

API = "/api/v1"
FIXTURE = Path(__file__).parent / "fixtures" / "llm" / "period.json"
TODAY = dt.date(2026, 10, 28)
# Eight months, two orders each; the total drops in May.
MONTHLY = [200, 210, 190, 205, 80, 85, 82, 84]
CSV = "ordered_on,region,amount\n" + "".join(
    f"2024-{m:02d}-{d:02d},{region},{total // 2}\n"
    for m, total in enumerate(MONTHLY, 1) for d, region in ((5, "North"), (20, "South"))
)
PAGE = {"title": "Spring trading report", "url": "https://news.example.org/spring", "score": 0.9,
        "content": "Shops across the region reported fewer orders through the spring of 2024."}
TAVILY = [{"kind": "search", "match": ["news"], "response": {"results": [PAGE]}}]


def result(rows, columns, truncated=False):
    return Result("r1", "SELECT 1", "SELECT 1", [{"name": n, "type": t} for n, t in columns], rows, len(rows),
                  truncated=truncated)


def months(values, start=(2024, 1)):
    y, m = start
    out = []
    for v in values:
        out.append([f"{y}-{m:02d}-01", v])
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


DATED = [("month", "DATE"), ("total", "DOUBLE")]


# --- the jump, in code ----------------------------------------------------------------------------

def test_a_big_drop_offers_the_later_months_period():
    button = period.offer(result(months(MONTHLY), DATED), TODAY)
    assert button == {"kind": "ask_period", "label": "What happened around May 2024?", "period": "May 2024",
                      "start_date": "2024-04-17", "end_date": "2024-06-14", "measure": "total", "result": "r1"}
    assert period.period_label(dt.date(2024, 4, 17), dt.date(2024, 6, 14)) == "May 2024"


def test_a_year_column_gives_a_year_and_its_whole_window():
    rows = [[2018, 100], [2019, 105], [2020, 98], [2021, 40], [2022, 44]]
    jump = period.find_jump(result(rows, [("year", "BIGINT"), ("sales", "BIGINT")]), TODAY)
    assert (jump.label, jump.start_date, jump.end_date, jump.measure) == ("2021", "2021-01-01", "2021-12-31", "sales")


def test_a_year_and_a_month_column_make_a_monthly_series():
    rows = [[2024, 11, 10], [2024, 12, 11], [2025, 1, 10], [2025, 2, 30], [2025, 3, 31]]
    jump = period.find_jump(result(rows, [("year", "INTEGER"), ("month", "INTEGER"), ("n", "BIGINT")]), TODAY)
    assert jump.label == "February 2025"


@pytest.mark.parametrize("kind, fmt", [("VARCHAR", "{y}-{m:02d}"), ("VARCHAR", "{y}-{m:02d}-01T00:00:00"), ("TIMESTAMP", "{y}-{m:02d}-01 00:00:00")])
def test_text_and_timestamp_time_columns_are_read(kind, fmt):
    rows = [[fmt.format(y=2024, m=m), v] for m, v in enumerate(MONTHLY, 1)]
    jump = period.find_jump(result(rows, [("month", kind), ("total", "DOUBLE")]), TODAY)
    assert jump and jump.label == "May 2024"


def test_the_series_may_arrive_in_any_order():
    rows = months(MONTHLY)[::-1]
    assert period.find_jump(result(rows, DATED), TODAY).label == "May 2024"


@pytest.mark.parametrize("name, res", [
    ("flat", result(months([100] * 8), DATED)),
    ("steady growth", result(months([100, 110, 120, 130, 140, 150]), DATED)),
    ("big in the series, small in itself", result(months([1000, 1001, 1002, 1003, 1100, 1101]), DATED)),
    ("a step no bigger than twice the usual one", result(months([100, 150, 100, 150, 100, 150]), DATED)),
    ("too few points", result(months([100, 40, 41]), DATED)),
    ("not over time", result([["North", 100], ["South", 5], ["East", 90], ["West", 95]], [("region", "VARCHAR"), ("total", "DOUBLE")])),
    ("a group beside the time", result([[*r, "A"] for r in months(MONTHLY)], [*DATED, ("region", "VARCHAR")])),
    ("two measures", result([[*r, 1] for r in months(MONTHLY)], [*DATED, ("n", "BIGINT")])),
    ("a date repeated", result(months(MONTHLY) + [["2024-01-01", 5]], DATED)),
    ("capped rows", result(months(MONTHLY), DATED, truncated=True)),
    ("a measure that isn't a number", result([[m, "x"] for m, _ in months(MONTHLY)], [("month", "DATE"), ("total", "VARCHAR")])),
])
def test_no_button_without_a_jump_in_a_dated_series(name, res):
    assert period.offer(res, TODAY) is None, name


def test_no_button_for_a_period_that_has_not_started():
    assert period.offer(result(months(MONTHLY), DATED), dt.date(2024, 3, 1)) is None


# --- the whole path -------------------------------------------------------------------------------

class Model(fixtures.FixtureTransport):
    pass


@pytest.fixture
def model(monkeypatch):
    """One fixture transport for every request, so a test can read the prompts."""
    shared = Model.load(FIXTURE)
    monkeypatch.setenv("LLM_MOCK", str(FIXTURE))
    monkeypatch.setattr(fixtures.FixtureTransport, "load", classmethod(lambda cls, path: shared))
    monkeypatch.setitem(ratelimit.LIMITS_PER_MINUTE, "llm", 100)
    get_settings.cache_clear()
    return shared


@pytest.fixture
def tavily(monkeypatch):
    fake = WebFixtureTransport(json.loads(json.dumps(TAVILY)))
    monkeypatch.setattr(web_client, "make_transport", lambda settings: fake)
    return fake


@pytest.fixture
def ds(run_jobs, model, client):
    d = client.post(f"{API}/datasets", files={"file": ("orders.csv", CSV.encode(), "text/csv")}).json()
    wait_status(client, d["id"], "offer", "ready")
    return d


def offers(msg):
    return [a for a in msg.get("actions", []) if a["kind"] == "ask_period"]


def test_a_dated_answer_with_a_jump_offers_the_button_and_the_press_sends_a_dated_news_search(ds, client, tavily, model):
    _, msg = send(client, ds["id"], "total amount by month")
    (button,) = offers(msg)
    assert button["label"] == "What happened around May 2024?"
    assert (button["start_date"], button["end_date"], button["measure"]) == ("2024-04-17", "2024-06-14", "total")
    assert tavily.calls == []  # offering costs no web call

    events, ans = send(client, ds["id"], button["label"], clarification_of=msg["id"], choice=button["label"])
    assert not [e for e, _ in events if e == "error"]
    (call,) = tavily.calls
    params = call["params"]
    assert call["kind"] == "search" and params["topic"] == "news" and params["include_answer"] is False
    assert (params["start_date"], params["end_date"]) == ("2024-04-17", "2024-06-14")
    assert params["query"] == "orders amount news May 2024"
    # Nothing of the file goes out: no region, no amount, no date of a row; the year is code's.
    sent = json.dumps(params)
    assert not any(v in sent for v in ("North", "South", "2024-05", "2024-01", "100", "105"))
    web = next(b for b in ans["blocks"] if b.get("labeled") == "web")
    runs = web["body"]["blocks"][0]["runs"]
    assert runs[0]["text"].startswith("From the web (not from your data)")
    assert {"type": "cite", "n": 1, "url": PAGE["url"], "title": PAGE["title"]} in runs
    texts = [r["text"] for r in runs if r["type"] == "text"][1:]
    assert all(not has_digits(t) and wording_problem(t) is None for t in texts)
    listing = next(b for b in ans["blocks"] if b["type"] == "web_sources")
    assert listing["query"] == params["query"] and "spring of 2024" in listing["results"][0]["snippet"]
    assert [s["kind"] for s in ans["sources"]] == ["web"]
    assert not offers(ans)  # one press, one answer
    thread = client.get(f"{API}/datasets/{ds['id']}/chat").json()
    assert thread[-2]["text"] == button["label"] and thread[-2]["clarification_of"] == msg["id"]
    calls = client.get(f"{API}/chat/messages/{ans['id']}/calls").json()["calls"]
    assert [(c["role"], c["purpose"]) for c in calls] == [("medium", "period_query"), ("web", "period_context"), ("medium", "web_answer")]
    prompt = next(c["prompt"] for c in model.calls if c["purpose"] == "period_query")
    assert "North" not in prompt and "<data>\ntotal\n</data>" not in prompt  # an alias isn't a column of the file


def test_the_period_is_read_from_the_saved_offer_not_from_the_request(ds, client, tavily):
    _, msg = send(client, ds["id"], "total amount by month")
    # A label that isn't a saved button is no button: the dated search doesn't run.
    resp = client.post(f"{API}/datasets/{ds['id']}/chat", json={"text": "What happened around June 1999?", "context": {"tab": "csv"},
                                                                 "clarification_of": msg["id"], "choice": "What happened around June 1999?"})
    assert resp.status_code == 200
    assert not [c for c in tavily.calls if "start_date" in c["params"]]


def test_no_button_when_the_web_is_off(ds, client):
    _, msg = send(client, ds["id"], "total amount by month")
    assert any(b["type"] == "chart" for b in msg["blocks"]) and offers(msg) == []


def test_no_button_for_an_answer_that_is_not_over_time(ds, client, tavily):
    _, msg = send(client, ds["id"], "total amount by region")
    assert any(b["type"] == "table" for b in msg["blocks"]) and offers(msg) == []


def test_a_failed_search_is_one_line(ds, client, monkeypatch):
    on = WebFixtureTransport(json.loads(json.dumps(TAVILY)))
    monkeypatch.setattr(web_client, "make_transport", lambda settings: on)
    _, msg = send(client, ds["id"], "total amount by month")
    (button,) = offers(msg)
    down = FailingTransport("timeout")
    monkeypatch.setattr(web_client, "make_transport", lambda settings: down)
    events, ans = send(client, ds["id"], button["label"], clarification_of=msg["id"], choice=button["label"])
    assert not [e for e, _ in events if e == "error"]
    assert ans["text"] == web_client.NOTES["timeout"] and len(ans["blocks"]) == 1 and ans["sources"] == []
    assert down.calls[0]["params"]["start_date"] == "2024-04-17"


def test_a_query_with_a_value_of_the_file_is_not_sent(ds, client, tavily):
    _, msg = send(client, ds["id"], "monthly total amount please")
    (button,) = offers(msg)
    _, ans = send(client, ds["id"], button["label"], clarification_of=msg["id"], choice=button["label"])
    assert "values from your file" in ans["text"] and tavily.calls == []
