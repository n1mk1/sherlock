"""The cleaning report (TRD §6.8, PRD CLEAN-6), assembled for one clean job from its checkpointed
state (`jobs.state_json`), the steps it committed, and the issues it handled. A run from a cleaning
plan adds `your_steps`: each step the user added, fix they rewrote or date order they picked, with
its outcome (PRD CLEAN-8b). `sources` lists each page the column notes and the checks cite, once (plan §3.5).

The counts say what became of each issue (PRD CLEAN-6): fixed, flagged, checked and kept (the Cleaner
looked and judged the values real), couldn't fix, not attempted (unticked, waiting on the user's
choice, or not reached before the budget ran out), and, apart, marked and not changed (leakage and
ID columns). A skip's line comes from its `skip_kind` (`loop.SKIP_KINDS`)."""

import json
import sqlite3

from sherlock.cleaning.plan import order_instruction
from sherlock.errors import not_found


def latest_clean_job(db: sqlite3.Connection, dataset_id: str) -> sqlite3.Row | None:
    return db.execute(
        "SELECT * FROM jobs WHERE dataset_id = ? AND kind = 'clean' ORDER BY created_at DESC, id DESC LIMIT 1",
        (dataset_id,),
    ).fetchone()


def build_report(db: sqlite3.Connection, dataset_id: str, job_id: str | None = None) -> dict:
    job = (db.execute("SELECT * FROM jobs WHERE id = ? AND dataset_id = ? AND kind = 'clean'", (job_id, dataset_id)).fetchone()
           if job_id else latest_clean_job(db, dataset_id))
    if job is None:
        raise not_found("No cleaning run yet")
    state = json.loads(job["state_json"]) if job["state_json"] else {}
    steps = db.execute("SELECT * FROM steps WHERE job_id = ? ORDER BY no", (job["id"],)).fetchall()
    from_version = state.get("from_version")
    found, start_keys = 0, set()
    if from_version is not None:
        rows = db.execute("SELECT detector, column FROM issues WHERE dataset_id = ? AND version = ?",
                          (dataset_id, from_version)).fetchall()
        found, start_keys = len(rows), {f"{r['detector']}|{r['column']}" for r in rows}
    ended_by = state.get("ended_by", "done")
    if job["status"] == "cancelled":
        ended_by = "stopped"
    elif job["status"] == "failed":
        ended_by = "error"
    to_version = steps[-1]["to_version"] if steps else from_version
    return {
        "job_id": job["id"],
        "status": job["status"],
        "from_version": from_version,
        "to_version": to_version,
        "ended_by": ended_by,
        "waited_for_model_s": state.get("waited_for_model_s", 0.0),
        "attempted": state.get("attempted", 0),
        "budget": {"max_steps": state.get("max_steps"), "max_seconds": state.get("max_seconds")},
        "started_at": job["started_at"],
        "finished_at": job["finished_at"],
        "counts": {
            "found": found,
            "fixed": sum(1 for s in steps if s["gate"] == "commit"),
            "flagged": sum(1 for s in steps if s["gate"] == "flag"),
            "skipped": len(state.get("skipped", [])),
            **_outcomes(state, start_keys),
            "rows_deleted": 0,
        },
        "steps": [{"step_id": s["id"], "no": s["no"], "summary": s["summary"], "gate": s["gate"],
                   "confidence": s["confidence"], "flag_reason": s["flag_reason"],
                   "impact": json.loads(s["impact_json"])} for s in steps],
        "skipped": state.get("skipped", []),
        "hand_edited_skipped": state.get("hand_edited_skipped", []),
        "decisions": [{"step_id": s["id"], **d} for s in steps for d in json.loads(s["decisions_json"])],
        "sources": _sources(db, dataset_id, steps),
        "your_steps": _your_steps(job, state),
        "error": job["error"],
    }


def _sources(db: sqlite3.Connection, dataset_id: str, steps: list[sqlite3.Row]) -> list[dict]:
    """The pages the dataset's column notes and the run's checks cite, each once by address, with its title and the
    day it was read (docs/plans/tavily.md §3.5). The notes come first, then the steps' evidence in step order."""
    seen: set[str] = set()
    out: list[dict] = []

    def add(url: str | None, title: str | None, retrieved_at: str | None) -> None:
        if url and url not in seen:
            seen.add(url)
            out.append({"url": url, "title": title, "retrieved_at": (retrieved_at or "")[:10]})

    for n in db.execute("SELECT source_url, source_title, retrieved_at FROM column_notes WHERE dataset_id = ? "
                        "ORDER BY column, kind", (dataset_id,)).fetchall():
        add(n["source_url"], n["source_title"], n["retrieved_at"])
    for s in steps:
        for d in json.loads(s["decisions_json"]):
            evidence = d.get("evidence") or {}
            add(evidence.get("url"), evidence.get("title"), evidence.get("retrieved_at"))
    return out


def _outcomes(state: dict, start_keys: set[str]) -> dict:
    """The skips by report line, plus the issues found at the start that the run never reached."""
    from sherlock.cleaning.loop import SKIP_KINDS

    lines = {"checked_and_kept": 0, "couldnt_fix": 0, "not_attempted": 0, "kept_by_design": 0}
    for s in state.get("skipped", []):
        line = SKIP_KINDS.get(s.get("skip_kind"))
        if line:
            lines[line] += 1
    lines["not_attempted"] += len(start_keys - set(state.get("handled", [])))
    return lines


def _your_steps(job: sqlite3.Row, state: dict) -> list[dict]:
    """The plan's requested items (steps the user added, fixes they rewrote) with what became of each:
    fixed, flagged or skipped with the reason, or `not_reached` when the run ended before them."""
    plan = json.loads(job["params_json"] or "{}").get("plan") or {}
    outcomes = state.get("plan_outcomes") or {}
    out = []
    for item in plan.get("items") or []:
        order = item.get("date_order")
        if not (item.get("ticked") and item.get("change") and (item.get("instruction") or order)):
            continue
        asked = " ".join(t for t in (item.get("instruction"), order and order_instruction(item["column"], order)) if t)
        got = outcomes.get(item["id"], {"outcome": "not_reached"})
        out.append({"item_id": item["id"], "column": item["column"], "instruction": asked,
                    "source": item["source"], "detector": item["detector"], **got})
    return out
