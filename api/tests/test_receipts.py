"""Receipts (TRD §4.9, §4.10): "How I worked it out" reads back the `llm_calls` of a chat message or a job."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sherlock.config import get_settings
from sherlock.db.connection import connect
from sherlock.db.util import now_iso
from sherlock.llm import calls
from sherlock.main import create_app
from tests.fixtures.messy import CSV
from tests.test_chat import send
from tests.test_jobs import db_rows, upload, wait_for, wait_status

API = "/api/v1"
LLM = Path(__file__).parent / "fixtures" / "llm"
pytestmark = pytest.mark.usefixtures("run_jobs")


def mock(monkeypatch, fixture: str) -> None:
    """Before the app is made, so its settings carry the fixture file."""
    monkeypatch.setenv("LLM_MOCK", str(LLM / fixture))
    get_settings.cache_clear()


def test_a_chat_answer_lists_its_calls_in_order(monkeypatch):
    mock(monkeypatch, "chat_titanic.json")
    app = create_app()
    with TestClient(app) as client, TestClient(app) as stranger:
        ds = client.post(f"{API}/datasets/sample").json()
        wait_status(client, ds["id"], "offer")
        client.post(f"{API}/datasets/{ds['id']}/use-as-is")
        wait_status(client, ds["id"], "ready")
        _, msg = send(client, ds["id"], "average fare by class")

        r = client.get(f"{API}/chat/messages/{msg['id']}/calls")
        assert r.status_code == 200, r.text
        receipt = r.json()
        steps = [(c["purpose"], c["role"]) for c in receipt["calls"]]
        assert steps[:3] == [("route", "small"), ("sql", "medium"), ("compose", "medium")]
        models = get_settings().models
        assert all(c["model"] == models[c["role"]] for c in receipt["calls"])
        logged = db_rows("SELECT id FROM llm_calls WHERE message_id = ? ORDER BY id", msg["id"])
        assert [c["id"] for c in receipt["calls"]] == [row["id"] for row in logged]
        assert all(c["ok"] and not c["cached"] and c["tokens"] == c["prompt_tokens"] + c["completion_tokens"]
                   for c in receipt["calls"])
        total = receipt["total"]
        assert total["calls"] == len(receipt["calls"]) and total["failed"] == 0 and total["cached"] == 0
        assert total["tokens"] == sum(c["tokens"] for c in receipt["calls"]) > 0
        assert total["latency_ms"] == sum(c["latency_ms"] for c in receipt["calls"])

        # The user's own message made no call; another user's message is not found.
        question = client.get(f"{API}/datasets/{ds['id']}/chat").json()[0]
        assert question["role"] == "user"
        assert client.get(f"{API}/chat/messages/{question['id']}/calls").json() == {
            "calls": [], "total": {"calls": 0, "failed": 0, "repaired": 0, "cached": 0, "prompt_tokens": 0,
                                   "completion_tokens": 0, "tokens": 0, "latency_ms": 0}}
        assert stranger.get(f"{API}/chat/messages/{msg['id']}/calls").status_code == 404
        assert client.get(f"{API}/chat/messages/msg_missing/calls").status_code == 404


def test_a_clean_lists_its_calls(monkeypatch):
    mock(monkeypatch, "cleaner_messy.json")
    app = create_app()
    with TestClient(app) as client, TestClient(app) as stranger:
        ds = upload(client, CSV, "messy.csv")
        wait_status(client, ds["id"], "offer", "failed")
        job = client.post(f"{API}/datasets/{ds['id']}/clean", json={}).json()
        wait_for(lambda: client.get(f"{API}/jobs/{job['id']}").json()["status"] in ("done", "failed"))

        receipt = client.get(f"{API}/jobs/{job['id']}/calls").json()
        assert {(c["purpose"], c["role"]) for c in receipt["calls"]} == {
            ("diagnose", "large"), ("propose", "large"), ("critic", "medium")}
        assert receipt["total"]["calls"] == len(receipt["calls"])
        assert receipt["total"]["tokens"] == sum(c["tokens"] for c in receipt["calls"])
        assert stranger.get(f"{API}/jobs/{job['id']}/calls").status_code == 404


def test_totals_count_failures_repairs_and_web_rows(client):
    db = connect(get_settings())
    try:
        rows = [
            # role, model, purpose, prompt, completion, latency, ok, error, repaired, cached
            ("medium", "nvidia/nemotron-test-super", "sql", 900, 100, 1200, 1, None, 0, 0),
            ("medium", "nvidia/nemotron-test-super", "sql", None, None, 30000, 0, "APITimeoutError: timed out", 0, 0),
            ("medium", "nvidia/nemotron-test-super", "sql", 1000, 50, 800, 1, None, 1, 0),
            ("web", "tavily-search", "web_search", None, None, 0, 1, None, 0, 1),
        ]
        for r in rows:
            db.execute("INSERT INTO llm_calls (job_id, role, model, purpose, prompt_tokens, completion_tokens, latency_ms, ok, "
                       "error, repaired, cached, created_at) VALUES ('job_x', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (*r, now_iso()))
        receipt = calls.for_job(db, "job_x")
    finally:
        db.close()
    assert [c.purpose for c in receipt.calls] == ["sql", "sql", "sql", "web_search"]
    assert receipt.calls[1].ok is False and receipt.calls[1].tokens == 0 and receipt.calls[1].error.startswith("APITimeout")
    assert receipt.calls[2].repaired and receipt.calls[3].cached and receipt.calls[3].role == "web"
    assert receipt.total.model_dump() == {"calls": 4, "failed": 1, "repaired": 1, "cached": 1, "prompt_tokens": 1900,
                                          "completion_tokens": 150, "tokens": 2050, "latency_ms": 32000}


def test_a_long_job_lists_the_first_calls_and_totals_them_all(client, monkeypatch):
    monkeypatch.setattr(calls, "MAX_LISTED", 3)
    db = connect(get_settings())
    try:
        for _ in range(5):
            db.execute("INSERT INTO llm_calls (job_id, role, model, purpose, prompt_tokens, completion_tokens, latency_ms, ok, "
                       "created_at) VALUES ('job_y', 'large', 'nvidia/nemotron-test-ultra', 'diagnose', 10, 5, 100, 1, ?)",
                       (now_iso(),))
        receipt = calls.for_job(db, "job_y")
        indexes = {r["name"] for r in db.execute("PRAGMA index_list(llm_calls)")}
    finally:
        db.close()
    assert len(receipt.calls) == 3 and receipt.total.calls == 5 and receipt.total.tokens == 75
    assert {"llm_calls_message", "llm_calls_job", "llm_calls_created"} <= indexes
