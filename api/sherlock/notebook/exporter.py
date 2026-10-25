"""The notebook exporter (TRD §7.7, PRD §7.12, App Flow §17): a dataset's current version as a
runnable Jupyter notebook that rebuilds it from the raw file.

`build()` assembles the cells; the `export_notebook` job writes the file and the `exports` row. An
export is cached by sha1(kind, version, state_rev, options): a new version or any widget, card,
run, layout or canvas change bumps `state_rev`, so a repeat export of the same state is instant.
"""

import hashlib
import json
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


class NotebookOptions(BaseModel):
    """TRD §4.2. Defaults `{ true, true, false, true, "steps_dashboard" }`."""
    model_config = ConfigDict(extra="forbid")
    include_data: bool = True
    include_cards: bool = True
    include_notes: bool = False
    include_runs: bool = True
    order: str = Field(default="steps_dashboard", pattern="^(steps_dashboard|flow_path)$")
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
    if dataset["status"] in ("cleaning", "building"):
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


def _widgets(db, dataset_id: str) -> list[sqlite3.Row]:
    """Live widgets in dashboard order: the saved layout's reading order, else builder order."""
    rows = db.execute("SELECT * FROM widgets WHERE dataset_id = ? AND deleted_at IS NULL ORDER BY order_no, created_at",
                      (dataset_id,)).fetchall()
    layout = db.execute("SELECT layout_json FROM layouts WHERE dataset_id = ?", (dataset_id,)).fetchone()
    if layout:
        pos = {it["i"]: (it["y"], it["x"]) for it in json.loads(layout[0]).get("lg", [])}
        rows = sorted(rows, key=lambda r: pos.get(r["id"], (10**9, r["order_no"])))
    return rows


def build(settings: Settings, db: sqlite3.Connection, cache: VersionConnections, dataset: sqlite3.Row,
          options: NotebookOptions, progress=lambda *_: None) -> Built:
    from sherlock.widgets import service as widgets

    chain, target, notes = _chain(db, dataset, options)
    version = target["version"]
    v1 = _version(db, dataset["id"], 1)
    v1_columns = json.loads(v1["columns_json"])
    import_options = json.loads(dataset["import_options_json"])
    used = sorted({h for s in chain for h in _helpers_used(db, s["id"])})
    rows = _widgets(db, dataset["id"]) if options.up_to_step is None else []
    if options.up_to_step is not None and _widgets(db, dataset["id"]):
        notes.append("Widgets are left out: they belong to the current version.")

    nb = new_notebook(metadata={
        "kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
        "language_info": {"name": "python"},
        "sherlock": {"version": version, "dataset_name": dataset["name"], "app_version": __version__,
                     "exported_at": datetime.now(UTC).isoformat(timespec="seconds")},
    })
    exported = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    progress(1, 3, "Writing the steps")
    nb.cells += cells.title(dataset["name"], version, exported, __version__, len(chain), len(rows), notes)
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

    progress(2, 3, f"Writing {len(rows)} widgets")
    env = widgets.Env(settings, db, cache, None)
    emitted = 0
    if rows:
        nb.cells.append(nbformat.v4.new_markdown_cell("## The dashboard\n\nEach widget's query runs on the rebuilt data."))
        nb.cells.append(nbformat.v4.new_code_cell(cells.PLOT_HELPERS))
    for w in rows:
        spec = json.loads(w["spec_json"])
        if spec["op"]["type"] != "sql":
            continue  # analysis widgets come with their runs (Implementation Plan D7.5)
        sql = widgets.compiled(env, dataset, spec, version, [])
        data = widgets.data(env, dataset, w, [], version)
        point = json.loads(w["point_json"])["key"] if w["point_json"] else None
        nb.cells += cells.widget(widgets.to_widget(w), sql, outputs.table(data["columns"], data["rows"], data["row_count"]), point)
        emitted += 1
    nb.cells += cells.closing()

    progress(3, 3, "Checking the notebook")
    nbformat.validate(nb)
    scan(nb)
    counts = {"steps": len(chain), "widgets": emitted, "runs": 0, "cards": 0}
    return Built(nb, version, counts, notes)


def _helpers_used(db, step_id: str) -> list[str]:
    row = db.execute("SELECT helpers_used_json FROM steps WHERE id = ?", (step_id,)).fetchone()
    return json.loads(row[0]) if row and row[0] else []


def preview(db: sqlite3.Connection, dataset: sqlite3.Row, options: NotebookOptions) -> dict:
    """What the dialog's sentence and notes need (TRD §4.2 preview), without building anything."""
    chain, target, notes = _chain(db, dataset, options)
    widgets = [w for w in _widgets(db, dataset["id"]) if json.loads(w["spec_json"])["op"]["type"] == "sql"]
    return {"version": target["version"], "notes": notes,
            "counts": {"steps": len(chain), "widgets": len(widgets) if options.up_to_step is None else 0,
                       "runs": 0, "cards": 0}}


def export_path(settings: Settings, dataset: sqlite3.Row, key: str) -> tuple[Path, str]:
    relative = f"exports/notebook_{key}.ipynb"
    return dataset_dir(settings, dataset["user_id"], dataset["id"]) / relative, relative
