"""Receipts (TRD §4.9, §4.10): the `llm_calls` rows of one chat message or one job, read back for
"How I worked it out", and the per-role spend the seed script prints.

A row is one request Sherlock made for someone: a Nemotron call (`role` large|medium|small|embed) or a
web request (`role = 'web'`, no tokens, `cached` when the web cache answered it with no request sent).
Every attempt is listed, failed and cut-off ones included, so the total is what the answer cost.
"""

import sqlite3

from pydantic import BaseModel

MAX_LISTED = 500  # a long clean makes a few hundred calls; the totals always count them all
ERROR_CHARS = 200

_COLUMNS = ("id, role, model, purpose, prompt_tokens, completion_tokens, latency_ms, ok, error, repaired, cached, "
            "created_at")
_TOTALS = ("COUNT(*) AS calls, COALESCE(SUM(1 - ok), 0) AS failed, COALESCE(SUM(repaired), 0) AS repaired, "
           "COALESCE(SUM(cached), 0) AS cached, COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens, "
           "COALESCE(SUM(completion_tokens), 0) AS completion_tokens, COALESCE(SUM(latency_ms), 0) AS latency_ms")


class ModelCall(BaseModel):
    id: int
    role: str                       # large | medium | small | embed | web
    model: str
    purpose: str
    prompt_tokens: int | None
    completion_tokens: int | None
    tokens: int                     # prompt + completion; 0 for a web request or a failed attempt
    latency_ms: int | None
    ok: bool
    error: str | None
    repaired: bool                  # the one repair call after a reply failed validation
    cached: bool                    # answered from a cache, no request sent (web rows)
    created_at: str


class CallTotals(BaseModel):
    calls: int
    failed: int
    repaired: int
    cached: int
    prompt_tokens: int
    completion_tokens: int
    tokens: int
    latency_ms: int                 # summed over the calls: the time spent waiting on them, not wall time


class Receipt(BaseModel):
    calls: list[ModelCall]          # oldest first, at most MAX_LISTED
    total: CallTotals               # over every call, listed or not


def to_call(row: sqlite3.Row) -> ModelCall:
    error = row["error"]
    return ModelCall(
        id=row["id"], role=row["role"], model=row["model"], purpose=row["purpose"],
        prompt_tokens=row["prompt_tokens"], completion_tokens=row["completion_tokens"],
        tokens=(row["prompt_tokens"] or 0) + (row["completion_tokens"] or 0), latency_ms=row["latency_ms"],
        ok=bool(row["ok"]), error=error[:ERROR_CHARS] if error else None, repaired=bool(row["repaired"]),
        cached=bool(row["cached"]), created_at=row["created_at"],
    )


def _receipt(db: sqlite3.Connection, where: str, value: str) -> Receipt:
    rows = db.execute(f"SELECT {_COLUMNS} FROM llm_calls WHERE {where} = ? ORDER BY id LIMIT ?",  # noqa: S608 - fixed columns
                      (value, MAX_LISTED)).fetchall()
    t = db.execute(f"SELECT {_TOTALS} FROM llm_calls WHERE {where} = ?", (value,)).fetchone()  # noqa: S608
    return Receipt(calls=[to_call(r) for r in rows], total=CallTotals(
        calls=t["calls"], failed=t["failed"], repaired=t["repaired"], cached=t["cached"],
        prompt_tokens=t["prompt_tokens"], completion_tokens=t["completion_tokens"],
        tokens=t["prompt_tokens"] + t["completion_tokens"], latency_ms=t["latency_ms"]))


def for_message(db: sqlite3.Connection, message_id: str) -> Receipt:
    """The calls made while answering one chat message (its assistant message's ID)."""
    return _receipt(db, "message_id", message_id)


def for_job(db: sqlite3.Connection, job_id: str) -> Receipt:
    """The calls one job made: a clean's diagnose, propose and critic calls, a build's curation, …"""
    return _receipt(db, "job_id", job_id)


def by_role(db: sqlite3.Connection) -> list[sqlite3.Row]:
    """Calls and tokens per role over the whole log (the seed script's spend line)."""
    return db.execute("SELECT role, count(*) AS n, sum(prompt_tokens) AS p, sum(completion_tokens) AS c "
                      "FROM llm_calls GROUP BY role ORDER BY role").fetchall()
