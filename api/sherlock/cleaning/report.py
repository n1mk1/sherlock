"""The cleaning report (TRD §6.8, PRD CLEAN-6), assembled for one clean job from its checkpointed
state (`jobs.state_json`), the steps it committed, and the issues it handled."""

import json
import sqlite3

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
    found = 0
    if from_version is not None:
        found = db.execute("SELECT count(*) FROM issues WHERE dataset_id = ? AND version = ?",
                           (dataset_id, from_version)).fetchone()[0]
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
        "counts": {
            "found": found,
            "fixed": sum(1 for s in steps if s["gate"] == "commit"),
            "flagged": sum(1 for s in steps if s["gate"] == "flag"),
            "skipped": len(state.get("skipped", [])),
            "rows_deleted": 0,
        },
        "steps": [{"step_id": s["id"], "no": s["no"], "summary": s["summary"], "gate": s["gate"],
                   "confidence": s["confidence"], "flag_reason": s["flag_reason"],
                   "impact": json.loads(s["impact_json"])} for s in steps],
        "skipped": state.get("skipped", []),
        "hand_edited_skipped": state.get("hand_edited_skipped", []),
        "decisions": [{"step_id": s["id"], **d} for s in steps for d in json.loads(s["decisions_json"])],
        "error": job["error"],
    }
