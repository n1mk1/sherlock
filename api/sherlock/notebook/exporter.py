"""The notebook exporter (TRD §7.7, PRD §7.12, App Flow §17): a dataset's current version as a
runnable Jupyter notebook that rebuilds it from the raw file.

`build()` assembles the cells; the `export_notebook` job writes the file and the `exports` row. An
export is cached by sha1(kind, version, state_rev, options): a new version or a run's change bumps
`state_rev`, so a repeat export of the same state is instant. An analysis that can't be emitted
becomes a Markdown cell saying why, so one run never fails the export.
"""

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import nbformat
from nbformat.v4 import new_notebook
from pydantic import BaseModel, ConfigDict, Field

from sherlock import __version__
from sherlock.config import Settings
from sherlock.notebook import cells, outputs
from sherlock.notebook.scan import scan
from sherlock.notebook.vendored_helpers import helpers_cell
from sherlock.steps.commit import load_step
from sherlock.storage import VersionConnections, dataset_dir

log = logging.getLogger("sherlock.notebook")


class NotebookOptions(BaseModel):
    """TRD §4.2. Defaults `{ include_data: true, include_runs: true }`."""
    model_config = ConfigDict(extra="forbid")
    include_data: bool = True
    include_runs: bool = True
    up_to_step: int | None = Field(default=None, ge=1)


@dataclass
class Built:
    nb: nbformat.NotebookNode
    version: int
    counts: dict
    notes: list[str]


def stem(name: str) -> str:
    import re

    return re.sub(r"\.(csv|tsv|txt)$", "", name.replace(" (sample)", ""), flags=re.I)


def file_name(dataset: sqlite3.Row, version: int) -> str:
    return cells.safe_name(f"{stem(dataset['name'])}-v{version}.ipynb")


def data_file(dataset: sqlite3.Row) -> str:
    return cells.safe_name(f"{stem(dataset['name'])}-raw.csv")


def cache_key(version: int, state_rev: int, options: NotebookOptions) -> str:
    raw = f"notebook:{version}:{state_rev}:{json.dumps(options.model_dump(), sort_keys=True)}"
    return hashlib.sha1(raw.encode()).hexdigest()


def _version(db, dataset_id: str, version: int) -> sqlite3.Row:
    return db.execute("SELECT * FROM versions WHERE dataset_id = ? AND version = ?", (dataset_id, version)).fetchone()


def _chain(db, dataset: sqlite3.Row, options: NotebookOptions) -> tuple[list[dict], sqlite3.Row, list[str]]:
    """The steps to emit and the version the assertion checks. With `up_to_step` the chain stops
    before that step and the check is against the version right before it."""
    current = _version(db, dataset["id"], dataset["current_version"])
    chain = [load_step(db, s) for s in json.loads(current["effective_step_ids_json"])]
    notes = []
    if dataset["status"] == "cleaning":
        notes.append(f"A job was still running when this was exported; it uses version {current['version']}, "
                     "the latest committed version.")
    if options.up_to_step is None:
        return chain, current, notes
    kept = [s for s in chain if s["no"] < options.up_to_step]
    target = None
    for row in db.execute("SELECT * FROM versions WHERE dataset_id = ? ORDER BY version DESC", (dataset["id"],)):
        if json.loads(row["effective_step_ids_json"]) == [s["id"] for s in kept]:
            target = row
            break
    if target is None:
        raise ValueError(f"No version holds the steps before step {options.up_to_step}.")
    notes.append(f"Exported up to step {options.up_to_step}: this notebook rebuilds version {target['version']}, "
                 f"not the current version {current['version']}.")
    return kept, target, notes


def build(settings: Settings, db: sqlite3.Connection, cache: VersionConnections, dataset: sqlite3.Row,
          options: NotebookOptions, progress=lambda *_: None) -> Built:
    chain, target, notes = _chain(db, dataset, options)
    version = target["version"]
    v1 = _version(db, dataset["id"], 1)
    v1_columns = json.loads(v1["columns_json"])
    import_options = json.loads(dataset["import_options_json"])
    used = sorted({h for s in chain for h in _helpers_used(db, s["id"])})
    runs = _runs(db, dataset["id"]) if options.include_runs and options.up_to_step is None else []
    if options.include_runs and options.up_to_step is not None and _runs(db, dataset["id"]):
        notes.append("Analyses are left out: they belong to the current version.")

    nb = new_notebook(metadata={
        "kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
        "language_info": {"name": "python"},
        "sherlock": {"version": version, "dataset_name": dataset["name"], "app_version": __version__,
                     "exported_at": datetime.now(UTC).isoformat(timespec="seconds")},
    })
    exported = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    progress(1, 3, "Writing the steps")
    nb.cells += cells.title(dataset["name"], version, exported, __version__, len(chain), len(runs), notes)
    nb.cells += cells.parameters(data_file(dataset), options.include_data)
    nb.cells += cells.requirements(settings.notebook_pins)
    nb.cells += cells.helpers(helpers_cell(used))
    nb.cells += cells.load(import_options, [c["name"] for c in v1_columns if c["name"] not in ("_row_id", "_quarantine_reason")],
                           {c["name"]: c["type"] for c in v1_columns})
    for s in chain:
        nb.cells += cells.step(s)
    in_chain = {s["id"] for s in chain}
    for u in db.execute("SELECT * FROM steps WHERE dataset_id = ? AND kind = 'undo' AND to_version <= ? ORDER BY no",
                        (dataset["id"], version)):
        undone = db.execute("SELECT no, id FROM steps WHERE id = ?", (u["undone_step_id"],)).fetchone()
        if undone and undone["id"] not in in_chain:
            nb.cells += cells.undo_note(dict(u), undone["no"])
    nb.cells += cells.assertion(version, target["row_count"], {c["name"]: c["type"] for c in json.loads(target["columns_json"])})

    progress(2, 3, f"Writing {len(runs)} analyses")
    if runs:
        intro = "## The analyses\n\nEach analysis runs its reproduction code on the rebuilt data."
        nb.cells.append(nbformat.v4.new_markdown_cell(intro))
        nb.cells.append(nbformat.v4.new_code_cell(cells.PLOT_HELPERS))
    emitted, failed = 0, 0
    for run in runs:
        title = f"What drives {run['target']}?"
        try:
            nb.cells += _run_cells(settings, dataset, run, title)
        except Exception as exc:  # noqa: BLE001 - one analysis never fails the export
            nb.cells += _failed(run, title, exc)
            failed += 1
        else:
            emitted += 1
    if failed:  # the first cell says so too
        notes.append(f"{failed} analys{'es' if failed != 1 else 'is'} couldn't be emitted and "
                     f"{'are' if failed != 1 else 'is'} left out; {'their cells say' if failed != 1 else 'its cell says'} why.")
        nb.cells[0] = cells.title(dataset["name"], version, exported, __version__, len(chain), emitted, notes)[0]
    nb.cells += cells.closing()

    progress(3, 3, "Checking the notebook")
    nbformat.validate(nb)
    scan(nb)
    return Built(nb, version, {"steps": len(chain), "runs": emitted}, notes)


MAX_RUNS = 10


def _runs(db, dataset_id: str) -> list[sqlite3.Row]:
    """Finished runs, newest first, at most ten; an outdated one says so in its cell (PRD NB-5)."""
    return db.execute("SELECT * FROM runs WHERE dataset_id = ? AND status IN ('done', 'outdated') AND repro_path IS NOT NULL "
                      "ORDER BY finished_at DESC LIMIT ?", (dataset_id, MAX_RUNS)).fetchall()


def _run_cells(settings: Settings, dataset: sqlite3.Row, run: sqlite3.Row, title: str) -> list:
    """The run's `repro.py` inlined (TRD §6.7) with its metrics, baselines and importance embedded
    from the run itself."""
    from nbformat.v4 import new_output

    from sherlock.ml import runner as ml

    card = json.loads(run["model_card_json"])
    code = (ml.run_folder(settings, dataset, run["id"]) / "repro.py").read_text(encoding="utf-8")
    metrics = new_output("stream", name="stdout", text=cells.metrics_text(card))
    names = ["name", "metric", "value"] + (["column"] if any("column" in b for b in card["baselines"]) else [])
    base = outputs.table([{"name": n} for n in names], [[b.get(n) for n in names] for b in card["baselines"]])
    imp = ml.results(settings, None, dataset, run, "importance")
    return cells.run(title, card, code, run["status"] == "outdated", metrics,
                     new_output("display_data", data=base["data"]),
                     outputs.table(imp["columns"], imp["rows"], imp["row_count"]))


def _failed(run: sqlite3.Row, title: str, exc: Exception) -> list:
    """An analysis that can't be emitted: a Markdown cell with the reason."""
    from sherlock.errors import ApiError

    reason = exc.message if isinstance(exc, ApiError) else (str(exc).strip().splitlines() or [type(exc).__name__])[0]
    log.warning("export: run %s can't be emitted: %s", run["id"], reason)
    return [nbformat.v4.new_markdown_cell(f"## {title}\n\n*This analysis can't be emitted: {reason[:300]} "
                                          "It's left out of the notebook; run it again in Sherlock and export again.*")]


def _helpers_used(db, step_id: str) -> list[str]:
    row = db.execute("SELECT helpers_used_json FROM steps WHERE id = ?", (step_id,)).fetchone()
    return json.loads(row[0]) if row and row[0] else []


def preview(db: sqlite3.Connection, dataset: sqlite3.Row, options: NotebookOptions) -> dict:
    """What the dialog's sentence and notes need (TRD §4.2 preview), without building anything."""
    chain, target, notes = _chain(db, dataset, options)
    runs = _runs(db, dataset["id"]) if options.include_runs and options.up_to_step is None else []
    return {"version": target["version"], "notes": notes, "counts": {"steps": len(chain), "runs": len(runs)}}


def export_path(settings: Settings, dataset: sqlite3.Row, key: str) -> tuple[Path, str]:
    relative = f"exports/notebook_{key}.ipynb"
    return dataset_dir(settings, dataset["user_id"], dataset["id"]) / relative, relative
