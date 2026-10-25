import json

import pytest

from sherlock.config import get_settings
from sherlock.db.connection import connect
from sherlock.db.util import now_iso
from sherlock.llm.client import (
    BudgetExceeded, CallScope, LLMClient, LLMUnavailable, StructuredOutputError, TransientError, Transport,
)
from sherlock.llm.fixtures import FixtureMiss, FixtureTransport, RecordingTransport
from sherlock.llm.schemas import Critique, Diagnosis, Story

DIAG = {"cause": "typed by hand", "approach_options": ["parse", "leave"], "preferred_option": 0,
        "risk": "low", "leave_as_is": False}


@pytest.fixture
def db(client):
    """Migrated database with one user and one job."""
    conn = connect(get_settings())
    now = now_iso()
    conn.execute("INSERT INTO users (id, cookie_token, created_at, last_seen_at) VALUES ('usr_1', 'x', ?, ?)", (now, now))
    conn.execute("INSERT INTO jobs (id, user_id, kind, status, created_at) VALUES ('job_1', 'usr_1', 'clean', 'running', ?)", (now,))
    yield conn
    conn.close()


def llm(entries, **kw):
    transport = FixtureTransport(entries)
    return LLMClient(get_settings(), transport=transport, sleep=lambda s: None, **kw), transport


def calls(db):
    return db.execute("SELECT * FROM llm_calls ORDER BY id").fetchall()


def test_structured_call_is_validated_logged_and_counted(db):
    client, transport = llm([{"purpose": "diagnose", "content": json.dumps(DIAG), "prompt_tokens": 120, "completion_tokens": 30}])
    scope = CallScope(user_id="usr_1", dataset_id="ds_1", job_id="job_1")
    out = client.structured("large", [{"role": "user", "content": "x"}], Diagnosis, purpose="diagnose", scope=scope)
    assert out.value.approach_options == ["parse", "leave"] and not out.repaired
    sent = transport.calls[0]
    assert sent["model"] == "nvidia/nemotron-test-ultra" and sent["temperature"] == 0.0
    assert sent["response_format"]["json_schema"]["strict"] is True
    assert sent["response_format"]["json_schema"]["name"] == "Diagnosis"
    assert "extra_body" not in sent  # reasoning stays on
    [row] = calls(db)
    assert (row["role"], row["purpose"], row["prompt_tokens"], row["completion_tokens"], row["ok"], row["repaired"]) == (
        "large", "diagnose", 120, 30, 1, 0)
    assert (row["user_id"], row["dataset_id"], row["job_id"]) == ("usr_1", "ds_1", "job_1")
    assert db.execute("SELECT tokens_used_today FROM users WHERE id = 'usr_1'").fetchone()[0] == 150
    assert db.execute("SELECT tokens_used FROM jobs WHERE id = 'job_1'").fetchone()[0] == 150


def test_reasoning_traces_are_stripped_before_parsing(db):
    client, _ = llm([{"purpose": "critic", "content": "<think>hmm {not json}</think>\n```json\n"
                      '{"changed_something_it_shouldnt": false, "concerns": []}\n```'}])
    out = client.structured("medium", [{"role": "user", "content": "x"}], Critique, purpose="critic")
    assert out.value.concerns == []


def test_one_repair_call_then_structured_output_error(db):
    bad = {**DIAG, "approach_options": ["only one"]}
    client, transport = llm([
        {"purpose": "diagnose", "content": json.dumps(bad)},
        {"purpose": "diagnose", "content": json.dumps(DIAG)},
    ])
    out = client.structured("large", [{"role": "user", "content": "x"}], Diagnosis, purpose="diagnose")
    assert out.repaired
    assert "failed validation" in transport.calls[1]["prompt"] and "approach_options" in transport.calls[1]["prompt"]
    assert [r["repaired"] for r in calls(db)] == [0, 1]

    client, _ = llm([{"purpose": "diagnose", "content": "no json here"}])
    with pytest.raises(StructuredOutputError):
        client.structured("large", [{"role": "user", "content": "x"}], Diagnosis, purpose="diagnose")


def test_story_prose_may_not_contain_digits(db):
    story = {"headline": [{"text": "First class paid "}, {"chip": "ratio"}, {"text": " times more"}],
             "body": [{"label": "column:fare"}, {"text": " is skewed."}]}
    client, _ = llm([{"purpose": "narrate", "content": json.dumps(story)}])
    assert client.structured("small", [], Story, purpose="narrate").value.headline[1].chip == "ratio"
    story["body"] = [{"text": "Fares rose 6 times."}]
    client, _ = llm([{"purpose": "narrate", "content": json.dumps(story)}])
    with pytest.raises(StructuredOutputError):
        client.structured("small", [], Story, purpose="narrate")


class Flaky(Transport):
    def __init__(self, failures: int) -> None:
        self.failures = failures

    def create(self, **kw):
        if self.failures:
            self.failures -= 1
            raise TransientError("429: slow down")
        return {"content": "pong", "tool_calls": [], "prompt_tokens": 1, "completion_tokens": 1}


def test_transient_errors_are_retried_with_backoff(db):
    slept, waits = [], []
    client = LLMClient(get_settings(), transport=Flaky(2), sleep=slept.append)
    c = client.complete("small", [], purpose="plain", scope=CallScope(on_wait=waits.append))
    assert c.text == "pong" and slept == [2.0, 4.0] and c.waited_s == 6.0
    assert waits == ["Waiting for the model…"] * 2
    assert [r["ok"] for r in calls(db)] == [0, 0, 1]

    client = LLMClient(get_settings(), transport=Flaky(10), sleep=slept.append)
    with pytest.raises(LLMUnavailable) as err:
        client.complete("small", [], purpose="plain")
    assert err.value.code == "llm_unavailable" and err.value.status == 503


def test_budgets(db, monkeypatch):
    client, _ = llm([{"purpose": "plain", "content": "ok", "prompt_tokens": 10, "completion_tokens": 10}])
    db.execute("UPDATE users SET tokens_used_today = 2000000, tokens_day = ? WHERE id = 'usr_1'", (now_iso()[:10],))
    with pytest.raises(BudgetExceeded) as err:
        client.complete("small", [], purpose="plain", scope=CallScope(user_id="usr_1"))
    assert err.value.code == "budget_exceeded"
    # A counter from an earlier day doesn't count.
    db.execute("UPDATE users SET tokens_day = '2000-01-01' WHERE id = 'usr_1'")
    client.complete("small", [], purpose="plain", scope=CallScope(user_id="usr_1"))
    assert db.execute("SELECT tokens_used_today FROM users WHERE id = 'usr_1'").fetchone()[0] == 20

    db.execute("UPDATE jobs SET tokens_used = 300000 WHERE id = 'job_1'")
    with pytest.raises(BudgetExceeded):
        client.complete("small", [], purpose="plain", scope=CallScope(job_id="job_1"))

    scope = CallScope(message_id="msg_1")
    client.complete("small", [], purpose="plain", scope=scope)
    assert scope.message_tokens == [20]
    scope.message_tokens[0] = 40000
    with pytest.raises(BudgetExceeded):
        client.complete("small", [], purpose="plain", scope=scope)


def test_reasoning_off_only_for_allowed_purposes(db):
    client, transport = llm([{"purpose": "route", "content": "{}"}, {"purpose": "narrate", "content": "{}"}])
    client.complete("small", [], purpose="route", reasoning=False)
    assert transport.calls[0]["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    with pytest.raises(ValueError):
        client.complete("small", [], purpose="narrate", reasoning=False)


def test_json_tools_mode_emulates_tool_calls(db, monkeypatch):
    monkeypatch.setenv("LLM_TOOLS_MODE", "json")
    get_settings.cache_clear()
    tools = [{"type": "function", "function": {"name": "ask_data", "parameters": {"type": "object"}}}]
    client, transport = llm([{"purpose": "plan", "content": '{"tool": "ask_data", "arguments": {"question": "q"}}'}])
    c = client.complete("medium", [{"role": "user", "content": "hi"}], purpose="plan", tools=tools)
    assert c.tool_calls == [{"id": "json", "name": "ask_data", "arguments": '{"question": "q"}'}]
    assert "tools" not in transport.calls[0] and "Choose one tool" in transport.calls[0]["prompt"]


def test_fixture_matching_order(tmp_path):
    t = FixtureTransport([
        {"purpose": "p", "match": ["age"], "content": "a1"},
        {"purpose": "p", "match": ["age"], "content": "a2"},
        {"purpose": "p", "content": "any"},
    ])
    ask = lambda text: t.create(model="m", messages=[{"content": text}], timeout=1, purpose="p")["content"]  # noqa: E731
    assert [ask("fix age"), ask("fix age"), ask("fix age"), ask("fix fare")] == ["a1", "a2", "a2", "any"]
    with pytest.raises(FixtureMiss):
        t.create(model="m", messages=[], timeout=1, purpose="other")

    path = tmp_path / "rec.json"
    rec = RecordingTransport(FixtureTransport([{"purpose": "p", "content": "x"}]), path)
    rec.create(model="m", messages=[], timeout=1, purpose="p")
    assert json.loads(path.read_text())[0]["content"] == "x"


def test_llm_mock_setting_loads_fixtures(tmp_path, monkeypatch, db):
    (tmp_path / "f.json").write_text(json.dumps([{"purpose": "plain", "content": "mocked"}]))
    monkeypatch.setenv("LLM_MOCK", str(tmp_path))
    get_settings.cache_clear()
    assert LLMClient(get_settings()).complete("small", [], purpose="plain").text == "mocked"
