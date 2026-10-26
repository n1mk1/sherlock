"""Receipts (TRD §4.9, §4.10): "How I worked it out" reads back the `llm_calls` of a chat message or a job;
and `sherlock llm stats` sums the log per purpose and role (TRD §14)."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sherlock.config import get_settings
from sherlock.db.connection import connect, sqlite_path
from sherlock.db.migrate import migrate
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


# --- `sherlock llm stats` ---------------------------------------------------------------------------


def seeded_db(rows):
    """A migrated database with these calls and no app running, so nothing else writes to it."""
    db = connect(get_settings())
    migrate(db)
    seed(db, rows)
    return db


def seed(db, rows):
    for r in rows:
        db.execute("INSERT INTO llm_calls (message_id, job_id, role, model, purpose, prompt_tokens, completion_tokens, latency_ms, "
                   "ok, repaired, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", r)


SEEDED = [
    # message, job, role, model, purpose, prompt, completion, latency, ok, repaired, created_at
    ("msg_a", None, "small", "nvidia/nano", "route", 300, 20, 1000, 1, 0, "2026-10-20T10:00:00.000Z"),
    ("msg_a", None, "medium", "nvidia/super", "sql", 1000, 200, 4000, 1, 0, "2026-10-20T10:00:01.000Z"),
    ("msg_a", None, "medium", "nvidia/super", "compose", 800, 100, 6000, 1, 0, "2026-10-20T10:00:05.000Z"),
    ("msg_b", None, "small", "nvidia/nano", "route", 300, 30, 3000, 1, 0, "2026-10-25T10:00:00.000Z"),
    ("msg_b", None, "medium", "nvidia/super", "sql", None, None, 30000, 0, 0, "2026-10-25T10:00:03.000Z"),
    ("msg_b", None, "medium", "nvidia/super", "sql", 1000, 100, 2000, 1, 0, "2026-10-25T10:00:40.000Z"),
    ("msg_b", None, "medium", "nvidia/super", "sql", 1100, 100, 3000, 1, 1, "2026-10-25T10:00:42.000Z"),
    (None, "job_c", "large", "nvidia/ultra", "diagnose", 2000, 1000, 2800, 1, 0, "2026-10-25T11:00:00.000Z"),
]


def test_llm_stats_per_purpose_and_role():
    db = seeded_db(SEEDED)
    try:
        everything = calls.stats(db)
        recent = calls.stats(db, days=3, now="2026-10-26T00:00:00.000Z")
    finally:
        db.close()
    assert everything["calls"] == 8 and recent["calls"] == 5
    sql = next(p for p in everything["purposes"] if p["purpose"] == "sql")
    # Latency over the three that answered (4000, 2000, 3000); the rates over all four attempts.
    assert sql["calls"] == 4 and sql["roles"] == ["medium"]
    assert sql["p50_latency_ms"] == 3000 and sql["p95_latency_ms"] == pytest.approx(3900)
    assert sql["tokens"] == 1200 + 1100 + 1200 and sql["mean_tokens"] == 1167
    assert sql["fail_rate"] == 0.25 and sql["repair_rate"] == pytest.approx(1 / 3) and sql["fallback_rate"] == 0
    assert [p["purpose"] for p in everything["purposes"]] == ["sql", "route", "compose", "diagnose"]  # most calls first
    small = next(r for r in everything["roles"] if r["role"] == "small")
    assert small["models"] == ["nvidia/nano"] and small["p50_latency_ms"] == 2000
    # Tokens per chat message: msg_a 2,420 and msg_b 2,630.
    assert everything["chat_messages"] == {"messages": 2, "p50_tokens": 2525, "p95_tokens": pytest.approx(2619.5)}
    assert recent["chat_messages"]["messages"] == 1
    table = calls.stats_table(everything)
    assert "| sql | medium | 4 | 3.0 | 3.9 | 1,167 | 3,500 | 33% | 25% | 0% |" in table
    assert "tokens per message p50 2,525" in table


def test_llm_stats_cli_reads_without_writing(capsys):
    from sherlock import cli

    seeded_db(SEEDED).close()
    path = sqlite_path(get_settings().database_url)
    before = path.stat().st_mtime_ns
    assert cli.main(["llm", "stats", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["calls"] == 8 and {r["role"] for r in out["roles"]} == {"small", "medium", "large"}
    assert cli.main(["llm", "stats", "--days", "3"]) == 0
    assert "Model calls over the last 3 days" in capsys.readouterr().out
    assert path.stat().st_mtime_ns == before


def test_a_fallback_call_shows_in_the_receipt_and_the_fallback_rate():
    db = seeded_db(SEEDED)
    try:
        db.execute("INSERT INTO llm_calls (message_id, role, model, purpose, prompt_tokens, completion_tokens, latency_ms, ok, "
                   "fallback_from, created_at) VALUES ('msg_b', 'large', 'nvidia/ultra', 'sql', 900, 100, 2500, 1, 'medium', "
                   "'2026-10-25T10:00:50.000Z')")
        receipt = calls.for_message(db, "msg_b")
        out = calls.stats(db)
    finally:
        db.close()
    assert [(c.role, c.fallback_from) for c in receipt.calls][-2:] == [("medium", None), ("large", "medium")]
    sql = next(p for p in out["purposes"] if p["purpose"] == "sql")
    assert sql["roles"] == ["large", "medium"] and sql["fallback_rate"] == pytest.approx(1 / 5)
    large = next(r for r in out["roles"] if r["role"] == "large")
    assert large["fallback_rate"] == pytest.approx(1 / 2)
