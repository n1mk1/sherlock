"""The grounding eval (PRD §3 "Unsourced numbers in generated text", STORY-3; TRD §14).

Each file is imported in a throwaway data directory, built with "Use as is", and its story cards
are written. Then every number on every widget card and the overview is checked:
- **Bound.** Each chip that isn't marked unverified names a fact of its card's current sheet, and
  shows that fact's formatted value.
- **Grounded.** The fact still holds: its query is run again on the version (or a derived fact is
  recomputed), with the 0.5% tolerance of `verify` (TRD §7.4 step 4).
- **No stray numbers.** No text run holds a digit, a Unicode number or a number in words, and every
  `value:` label names a value that is in its column.
The PRD target is 100% grounded. It uses the real model unless `LLM_MOCK` is set.
"""

import os
import sqlite3
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

API = "/api/v1"
SETS = ["titanic3.csv", "sales_dated.csv"]


@dataclass
class Result:
    dataset: str
    cards: int = 0
    by_model: int = 0
    chips: int = 0
    grounded: int = 0
    problems: list[str] = field(default_factory=list)
    llm_calls: int = 0
    tokens: int = 0


def _settle(client, ds_id: str, timeout_s: float = 900) -> None:
    """Wait until no job of the dataset is queued or running (the build, stories, the driver run)."""
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        jobs = client.get(f"{API}/jobs?dataset_id={ds_id}").json()
        if isinstance(jobs, list) and jobs and all(j["status"] in ("done", "failed", "cancelled") for j in jobs):
            if any(j["kind"] == "stories" for j in jobs):
                return
        time.sleep(1)
    raise TimeoutError("the dataset's jobs didn't finish")


def _runs(card: dict) -> list[dict]:
    return [r for part in (card["headline"], card["body"]) for b in part.get("blocks", []) for r in b["runs"]]


def check_dataset(client, db: sqlite3.Connection, settings, filename: str, ds_id: str) -> Result:
    import duckdb

    from sherlock.llm.text import has_digits
    from sherlock.rows.query import ident
    from sherlock.stories import facts as fx
    from sherlock.stories import narrate as nr
    from sherlock.stories import service as stories
    from sherlock.storage import dataset_dir, sql_path

    res = Result(filename)
    dataset = db.execute("SELECT * FROM datasets WHERE id = ?", (ds_id,)).fetchone()
    conn = duckdb.connect()
    vrow = db.execute("SELECT parquet_path FROM versions WHERE dataset_id = ? AND version = ?",
                      (ds_id, dataset["current_version"])).fetchone()
    parquet = dataset_dir(settings, dataset["user_id"], ds_id) / vrow["parquet_path"]
    conn.execute(f"CREATE TABLE t AS SELECT * FROM read_parquet({sql_path(parquet)})")
    columns = {r[0] for r in conn.execute("DESCRIBE t").fetchall()}
    for card in client.get(f"{API}/datasets/{ds_id}/cards").json():
        if card["kind"] not in ("overview", "widget"):
            continue
        res.cards += 1
        res.by_model += bool(card["narrated_by"])
        sheet = stories.get_sheet(db, card["fact_sheet_id"]) or {"facts": {}}
        name = card["kind"] if card["kind"] == "overview" else f"widget {card['widget_id']}"
        # A card the user edited holds their words: its text isn't the model's, and its chips show the
        # latest sheet's values (TRD §4.6), not the ones stored when the user saved.
        edited = card["edited_by_user"]
        for run in _runs(card):
            if run["type"] == "text":
                if not edited and (has_digits(run["text"]) or nr.number_in_words(run["text"])):
                    res.problems.append(f"{filename} · {name}: a number in a text run: {run['text']!r}")
            elif run["type"] == "label" and run["ref"].startswith("value:"):
                col, _, val = run["ref"][6:].partition(":")
                found = col in columns and conn.execute(
                    f"SELECT 1 FROM t WHERE CAST({ident(col)} AS VARCHAR) = ? LIMIT 1", [val]).fetchone()
                if not found:
                    res.problems.append(f"{filename} · {name}: the label {run['ref']!r} names no value of the file")
            elif run["type"] == "chip" and not run.get("unverified"):
                res.chips += 1
                key = run.get("key") or ""
                f = sheet["facts"].get(key)
                if f is None or (not edited and card["facts"].get(key, {}).get("formatted") != run["value"]):
                    res.problems.append(f"{filename} · {name}: the chip {key!r} ({run['value']}) isn't its fact's value")
                    continue
                # An overview fact is `w<i>.<key>`; a derived one names its sources without the prefix.
                prefix, _, bare = key.rpartition(".")
                scope = {k.rpartition(".")[2]: v for k, v in sheet["facts"].items() if k.startswith(prefix + ".")} if prefix \
                    else sheet["facts"]
                if fx.verify(conn, scope, [bare]):
                    res.problems.append(f"{filename} · {name}: the chip {key!r} ({run['value']}) no longer holds")
                    continue
                res.grounded += 1
    calls = db.execute("SELECT COUNT(*), COALESCE(SUM(prompt_tokens + completion_tokens), 0) FROM llm_calls "
                       "WHERE dataset_id = ?", (ds_id,)).fetchone()
    res.llm_calls, res.tokens = calls[0], calls[1]
    return res


def report(results: list[Result]) -> str:
    lines = ["| File | Cards | By the model | Chips | Grounded | Problems | `llm_calls` | Tokens |",
             "|---|---|---|---|---|---|---|---|"]
    for r in results:
        share = f"{r.grounded / r.chips:.0%}" if r.chips else "n/a"
        lines.append(f"| {r.dataset} | {r.cards} | {r.by_model} | {r.chips} | {r.grounded} ({share}) | {len(r.problems)} "
                     f"| {r.llm_calls} | {r.tokens:,} |")
    problems = [p for r in results for p in r.problems]
    chips, grounded = sum(r.chips for r in results), sum(r.grounded for r in results)
    lines += ["", f"Grounded {grounded} of {chips} chips. Problems: {len(problems)}."]
    lines += [f"- {p}" for p in problems]
    return "\n".join(lines)


def run(only: list[str] | None = None) -> str:
    from fastapi.testclient import TestClient

    from sherlock.config import get_settings
    from sherlock.eval.ask import ready
    from sherlock.main import create_app

    results = []
    with tempfile.TemporaryDirectory(prefix="sherlock-eval-") as tmp:
        os.environ["DATA_DIR"] = tmp
        os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmp, 'sherlock.db').as_posix()}"
        os.environ.setdefault("JOB_WORKERS", "2")
        get_settings.cache_clear()
        settings = get_settings()
        with TestClient(create_app()) as client:
            for filename in only or SETS:
                ds_id = ready(client, filename)
                _settle(client, ds_id)
                db = sqlite3.connect(Path(tmp, "sherlock.db"))
                db.row_factory = sqlite3.Row
                try:
                    results.append(check_dataset(client, db, settings, filename, ds_id))
                finally:
                    db.close()
        get_settings.cache_clear()
    return report(results)
