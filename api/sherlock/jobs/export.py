"""The `export_notebook` job (TRD §7.7, PRD NB-9): build the notebook, write it under the dataset's
`exports/`, and mark the `exports` row done with its download URL."""

import asyncio
import json
import sqlite3

import nbformat

from sherlock.db.util import now_iso
from sherlock.jobs.events import EventBus
from sherlock.jobs.runner import JobContext, register
from sherlock.notebook.exporter import NotebookOptions, build, export_path


def _export(ctx: JobContext) -> dict:
    export = ctx.db.execute("SELECT * FROM exports WHERE id = ?", (ctx.params["export_id"],)).fetchone()
    dataset = ctx.db.execute("SELECT * FROM datasets WHERE id = ?", (export["dataset_id"],)).fetchone()
    ctx.db.execute("UPDATE exports SET status = 'running', job_id = ? WHERE id = ?", (ctx.id, export["id"]))
    options = NotebookOptions.model_validate(json.loads(export["options_json"]))
    built = build(ctx.settings, ctx.db, ctx.cache, dataset, options, progress=ctx.progress)
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
