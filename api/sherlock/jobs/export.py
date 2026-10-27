"""The `export_notebook` job (TRD §7.7, PRD NB-9): build the notebook, write it under the dataset's
`exports/`, and mark the `exports` row done with its download URL.

An export never mixes two versions' cards silently: while a cascade, stories job or build is
queued or running for the dataset, it waits up to `WAIT_S`; if they're still busy, the notebook says
the cards were being updated (and each card that isn't current carries its own note)."""

import asyncio
import json
import sqlite3
import time

import nbformat

from sherlock.db.util import now_iso
from sherlock.jobs.events import EventBus
from sherlock.jobs.runner import SERIAL_KINDS, JobContext, register
from sherlock.notebook.exporter import NotebookOptions, build, export_path

WAIT_S = 20.0  # how long an export waits for its dataset's cards to finish updating
POLL_S = 0.5
UPDATING_NOTE = ("Story cards were still being updated when this was exported, so some may show an earlier version's "
                 "words; each card that isn't current says so. Export again once the update finishes.")


def updating(db: sqlite3.Connection, dataset_id: str) -> bool:
    """A job that writes the dataset's widgets or cards (a cascade, stories job or build) is queued or running."""
    kinds = ", ".join(f"'{k}'" for k in SERIAL_KINDS)
    return db.execute(f"SELECT 1 FROM jobs WHERE dataset_id = ? AND kind IN ({kinds}) AND status IN ('queued', 'running') "  # noqa: S608
                      "LIMIT 1", (dataset_id,)).fetchone() is not None


def _export(ctx: JobContext) -> dict:
    export = ctx.db.execute("SELECT * FROM exports WHERE id = ?", (ctx.params["export_id"],)).fetchone()
    ctx.db.execute("UPDATE exports SET status = 'running', job_id = ? WHERE id = ?", (ctx.id, export["id"]))
    options = NotebookOptions.model_validate(json.loads(export["options_json"]))
    deadline = time.monotonic() + WAIT_S
    if updating(ctx.db, export["dataset_id"]):
        ctx.log("Waiting for the story cards to finish updating…", icon="wait")
        while updating(ctx.db, export["dataset_id"]) and time.monotonic() < deadline:
            time.sleep(POLL_S)
    notes = [UPDATING_NOTE] if options.include_cards and updating(ctx.db, export["dataset_id"]) else []
    dataset = ctx.db.execute("SELECT * FROM datasets WHERE id = ?", (export["dataset_id"],)).fetchone()  # after the wait
    built = build(ctx.settings, ctx.db, ctx.cache, dataset, options, progress=ctx.progress, extra_notes=notes)
    path, relative = export_path(ctx.settings, dataset, export["cache_key"])
    path.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(built.nb, str(path))
    ctx.db.execute(
        "UPDATE exports SET status = 'done', path = ?, bytes = ?, counts_json = ?, version = ?, finished_at = ? "
        "WHERE id = ?",
        (relative, path.stat().st_size, json.dumps(built.counts), built.version, now_iso(), export["id"]),
    )
    return {"export_id": export["id"], "download_url": f"/api/v1/exports/{export['id']}/download",
            "counts": built.counts, "version": built.version}


async def run(ctx: JobContext) -> dict:
    return await asyncio.to_thread(_export, ctx)


def on_failure(db: sqlite3.Connection, bus: EventBus | None, job: sqlite3.Row, message: str) -> None:
    params = json.loads(job["params_json"])
    db.execute("UPDATE exports SET status = 'failed', error = ?, finished_at = ? WHERE id = ?",
               (message, now_iso(), params.get("export_id")))


register("export_notebook", run, on_failure)
