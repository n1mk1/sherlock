"""Receipts (TRD §4.9, §4.10): the `llm_calls` rows of one chat message or one job, read back for
"How I worked it out"; the per-role spend the seed script prints; and `sherlock llm stats` (TRD §14).

A row is one request Sherlock made for someone: a Nemotron call (`role` large|medium|small|embed) or a
web request (`role = 'web'`, no tokens, `cached` when the web cache answered it with no request sent).
Every attempt is listed, failed and cut-off ones included, so the total is what the answer cost.
"""

import sqlite3
from datetime import datetime, timedelta

from pydantic import BaseModel

from sherlock.db.util import now_iso

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


# --- `sherlock llm stats` (TRD §14) -----------------------------------------------------------------


def percentile(values: list[float], q: float) -> float | None:
    """The q-th percentile (0–100) by linear interpolation between the closest ranks, or None for no values."""
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * q / 100
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def _rates(rows: list[sqlite3.Row]) -> dict:
    """Latency and token figures, and the rates, of one group of calls. Latency and tokens are over the
    calls that answered (`ok`); the rates are over every attempt."""
    answered = [r for r in rows if r["ok"]]
    latencies = [r["latency_ms"] for r in answered if r["latency_ms"] is not None]
    tokens = [(r["prompt_tokens"] or 0) + (r["completion_tokens"] or 0) for r in answered]
    firsts = sum(1 for r in rows if not r["repaired"])  # each repair follows one first try that failed validation
    n = len(rows)
    return {
        "calls": n,
        "p50_latency_ms": percentile(latencies, 50),
        "p95_latency_ms": percentile(latencies, 95),
        "mean_tokens": round(sum(tokens) / len(tokens)) if tokens else None,
        "tokens": sum(tokens),
        "repair_rate": (sum(1 for r in rows if r["repaired"]) / firsts) if firsts else 0.0,
        "fail_rate": sum(1 for r in rows if not r["ok"]) / n if n else 0.0,
        "fallback_rate": sum(1 for r in rows if r["fallback_from"]) / n if n else 0.0,
    }


def stats(db: sqlite3.Connection, days: float | None = None, now: str | None = None) -> dict:
    """Per purpose and per role over the last `days` days (all of the log with None): p50/p95 latency,
    tokens, and the repair, fail and fallback rates; plus the tokens per chat message."""
    have = {r[1] for r in db.execute("PRAGMA table_info(llm_calls)")}
    fallback = "fallback_from" if "fallback_from" in have else "NULL AS fallback_from"  # before migration 007
    where, params = "", []
    if days is not None:
        since = datetime.fromisoformat((now or now_iso()).replace("Z", "+00:00")) - timedelta(days=days)
        where, params = "WHERE created_at >= ?", [since.strftime("%Y-%m-%dT%H:%M:%S.000Z")]
    rows = db.execute(f"SELECT role, model, purpose, message_id, prompt_tokens, completion_tokens, latency_ms, ok, "  # noqa: S608
                      f"repaired, {fallback}, created_at FROM llm_calls {where} ORDER BY id", params).fetchall()
    by_purpose: dict[str, list] = {}
    by_role: dict[str, list] = {}
    per_message: dict[str, int] = {}
    for r in rows:
        by_purpose.setdefault(r["purpose"], []).append(r)
        by_role.setdefault(r["role"], []).append(r)
        if r["message_id"]:  # a chat answer's calls (and the Add widget drawer's "Describe it")
            spent = (r["prompt_tokens"] or 0) + (r["completion_tokens"] or 0)
            per_message[r["message_id"]] = per_message.get(r["message_id"], 0) + spent
    message_tokens = list(per_message.values())
    return {
        "days": days,
        "since": params[0] if params else (rows[0]["created_at"] if rows else None),
        "until": rows[-1]["created_at"] if rows else None,
        "calls": len(rows),
        "purposes": [{"purpose": p, "roles": sorted({r["role"] for r in group}), **_rates(group)}
                     for p, group in sorted(by_purpose.items(), key=lambda kv: (-len(kv[1]), kv[0]))],
        "roles": [{"role": role, "models": sorted({r["model"] for r in group}), **_rates(group)}
                  for role, group in sorted(by_role.items())],
        "chat_messages": {"messages": len(message_tokens), "p50_tokens": percentile(message_tokens, 50),
                          "p95_tokens": percentile(message_tokens, 95)},
    }


def _s(ms: float | None) -> str:
    return "" if ms is None else f"{ms / 1000:.1f}"


def _n(x: float | None) -> str:
    return "" if x is None else f"{x:,.0f}"


def _pct(x: float) -> str:
    return f"{100 * x:.0f}%" if x >= 0.01 or x == 0 else "<1%"


def stats_table(s: dict) -> str:
    """The stats as markdown: a table per purpose, one per role, and the chat messages' tokens."""
    span = f"the last {s['days']:g} days" if s["days"] is not None else "the whole log"
    lines = [f"Model calls over {span}: {s['calls']:,} ({s['since'] or '-'} to {s['until'] or '-'}). Latency and tokens "
             "are over the calls that answered; the rates over every attempt.", ""]
    head = "| calls | p50 s | p95 s | tokens per call | tokens | repair | fail | fallback |"
    lines += ["| purpose | roles " + head, "|---|---" + "|---:" * 8 + "|"]
    for p in s["purposes"]:
        lines.append(f"| {p['purpose']} | {', '.join(p['roles'])} | {p['calls']:,} | {_s(p['p50_latency_ms'])} | "
                     f"{_s(p['p95_latency_ms'])} | {_n(p['mean_tokens'])} | {p['tokens']:,} | {_pct(p['repair_rate'])} | "
                     f"{_pct(p['fail_rate'])} | {_pct(p['fallback_rate'])} |")
    lines += ["", "| role | models " + head, "|---|---" + "|---:" * 8 + "|"]
    for r in s["roles"]:
        lines.append(f"| {r['role']} | {', '.join(r['models'])} | {r['calls']:,} | {_s(r['p50_latency_ms'])} | "
                     f"{_s(r['p95_latency_ms'])} | {_n(r['mean_tokens'])} | {r['tokens']:,} | {_pct(r['repair_rate'])} | "
                     f"{_pct(r['fail_rate'])} | {_pct(r['fallback_rate'])} |")
    m = s["chat_messages"]
    lines += ["", f"Chat messages with model calls: {m['messages']:,}; tokens per message p50 {m['p50_tokens'] or 0:,.0f}, "
              f"p95 {m['p95_tokens'] or 0:,.0f}."]
    return "\n".join(lines)
