"""The notebook exporter (TRD §7.7, PRD §7.12, App Flow §17): a dataset's current version as a
runnable Jupyter notebook that rebuilds it from the raw file.

`build()` assembles the cells; the `export_notebook` job writes the file and the `exports` row. An
export is cached by sha1(kind, version, state_rev, options): a new version or any widget, card,
run, layout or canvas change bumps `state_rev`, so a repeat export of the same state is instant. A
cascade bumps it when it starts and when it ends, and so does a deleted card (plan 1.4). A widget that
fails on the version becomes a Markdown cell saying why, so one widget never fails the export.
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
          options: NotebookOptions, progress=lambda *_: None, extra_notes: list[str] | None = None) -> Built:
    """`extra_notes` go into the first cell with the others (the export job's "cards were updating")."""
    from sherlock.widgets import service as widgets

    chain, target, notes = _chain(db, dataset, options)
    notes += extra_notes or []
    version = target["version"]
    v1 = _version(db, dataset["id"], 1)
    v1_columns = json.loads(v1["columns_json"])
    import_options = json.loads(dataset["import_options_json"])
    used = sorted({h for s in chain for h in _helpers_used(db, s["id"])})
    rows = _widgets(db, dataset["id"]) if options.up_to_step is None else []
    if options.up_to_step is not None and _widgets(db, dataset["id"]):
        notes.append("Widgets are left out: they belong to the current version.")
    cards = _cards(db, dataset) if options.include_cards and options.up_to_step is None else {}
    if options.include_cards and not cards and options.up_to_step is None:
        notes.append("There are no story cards yet, so this notebook has the widgets only.")

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
    if "overview" in cards:
        nb.cells += _card(cards["overview"], level="##")
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
    emitted, emitted_runs = 0, []
    extra = _extra_runs(db, dataset["id"], rows) if options.include_runs and options.up_to_step is None else []
    if rows or extra:
        intro = "## The dashboard\n\nEach widget's query runs on the rebuilt data; each analysis runs its reproduction code."
        nb.cells.append(nbformat.v4.new_markdown_cell(intro))
        nb.cells.append(nbformat.v4.new_code_cell(cells.PLOT_HELPERS))
    failed = 0
    for w in rows:
        spec = json.loads(w["spec_json"])
        if spec["op"]["type"] != "sql":
            run = _finished_run(db, w["run_id"])
            if run is None:
                nb.cells.append(nbformat.v4.new_markdown_cell(
                    f"## {w['title']}\n\n*This analysis hadn't finished when the notebook was exported, so it's left out.*"))
                continue
            try:
                made = _run_cells(settings, dataset, run, w["title"])  # an analysis widget is emitted via its run
            except Exception as exc:  # noqa: BLE001 - one widget never fails the export (plan 1.4)
                nb.cells += _failed(w, version, exc)
                failed += 1
                continue
            nb.cells += made
            emitted_runs.append(run["id"])
            if w["id"] in cards:
                nb.cells += _card(cards[w["id"]])
            continue
        try:
            sql = widgets.compiled(env, dataset, spec, version, [])
            data = widgets.data(env, dataset, w, [], version)
        except Exception as exc:  # noqa: BLE001 - one widget never fails the export (plan 1.4)
            nb.cells += _failed(w, version, exc)
            failed += 1
        else:
            point = json.loads(w["point_json"])["key"] if w["point_json"] else None
            nb.cells += cells.widget(widgets.to_widget(w), sql, outputs.table(data["columns"], data["rows"], data["row_count"]),
                                     point)
            emitted += 1
        if w["id"] in cards:
            nb.cells += _card(cards[w["id"]])
    if failed:  # the first cell says so too
        notes.append(f"{failed} widget{'s' if failed != 1 else ''} failed on version {version} and "
                     f"{'are' if failed != 1 else 'is'} left out; {'their cells say' if failed != 1 else 'its cell says'} why.")
        nb.cells[0] = cells.title(dataset["name"], version, exported, __version__, len(chain), len(rows), notes)[0]
    for run in extra:  # include_runs: finished runs no widget shows
        nb.cells += _run_cells(settings, dataset, run, f"What drives {run['target']}?")
        emitted_runs.append(run["id"])
    flow_cards = _flow_cards(db, dataset) if options.include_cards and options.up_to_step is None else []
    flow_notes = _canvas_notes(db, dataset["id"]) if options.include_notes else []
    if flow_cards or flow_notes:
        nb.cells += cells.flow_intro(len(flow_cards), len(flow_notes))
        for entry in flow_cards:
            nb.cells += _card(entry)
        for text in flow_notes:
            nb.cells += cells.note(text)
    nb.cells += cells.closing()

    progress(3, 3, "Checking the notebook")
    nbformat.validate(nb)
    scan(nb)
    counts = {"steps": len(chain), "widgets": emitted, "runs": len(emitted_runs), "cards": len(cards) + len(flow_cards),
              "notes": len(flow_notes)}
    return Built(nb, version, counts, notes)


MAX_EXTRA_RUNS = 10


def _finished_run(db, run_id: str | None) -> sqlite3.Row | None:
    if not run_id:
        return None
    return db.execute("SELECT * FROM runs WHERE id = ? AND status IN ('done', 'outdated') AND repro_path IS NOT NULL",
                      (run_id,)).fetchone()


def _extra_runs(db, dataset_id: str, rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    """Finished runs that no live widget shows, newest first (at most ten). A widget's earlier runs
    (before a re-run or a change of settings) are left out: the widget is emitted with its current one."""
    live = {w["id"] for w in rows}
    shown = {w["run_id"] for w in rows if w["run_id"] and json.loads(w["spec_json"])["op"]["type"] == "ml"}
    out = db.execute("SELECT * FROM runs WHERE dataset_id = ? AND status IN ('done', 'outdated') AND repro_path IS NOT NULL "
                     "ORDER BY finished_at DESC", (dataset_id,)).fetchall()
    return [r for r in out if r["id"] not in shown and r["widget_id"] not in live][:MAX_EXTRA_RUNS]


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


def _failed(widget: sqlite3.Row, version: int, exc: Exception) -> list:
    """A widget whose query or run can't be emitted on this version: a Markdown cell with the reason."""
    from sherlock.errors import ApiError

    reason = exc.message if isinstance(exc, ApiError) else (str(exc).strip().splitlines() or [type(exc).__name__])[0]
    log.warning("export: widget %s fails on v%s: %s", widget["id"], version, reason)
    return [nbformat.v4.new_markdown_cell(f"## {widget['title']}\n\n*This widget fails on version {version}: {reason[:300]} "
                                          "It's left out of the notebook; fix it in Sherlock and export again.*")]


def _card(entry: tuple[dict, dict, str | None], level: str = "###") -> list:
    c, facts, stale = entry
    return cells.card(c, facts, level=level, stale=stale)


def stale_note(why: str | None, card: dict, version: int) -> str | None:
    """The note under a card that isn't usable (plan 1.3): its words may not match the numbers."""
    if why is None:
        return None
    written = f" It was written for version {card['version']}; this notebook rebuilds version {version}."         if card["version"] < version else ""
    return (f"Out of date ({why}): its words may not match the numbers shown.{written} "
            "Refresh it in Sherlock to bring it up to date.")


def _cards(db, dataset: sqlite3.Row) -> dict:
    """widget_id (or "overview") → (card, facts, stale note) for the live cards (TRD §7.7)."""
    from sherlock.stories import service as stories
    from sherlock.stories import trust

    t = trust.Trust(db, dataset)
    out = {}
    for r in db.execute("SELECT * FROM cards WHERE dataset_id = ? AND deleted_at IS NULL AND kind IN ('overview', 'widget')",
                        (dataset["id"],)):
        c = stories.to_card(db, r)
        sheet = stories.get_sheet(db, c["fact_sheet_id"])
        why = t.why_not(r)
        out["overview" if c["kind"] == "overview" else c["widget_id"]] = (
            c, (sheet or {}).get("facts", {}), stale_note(None if why == trust.WIDGET_DELETED else why, c, dataset["current_version"]))
    return out


def _flow_cards(db, dataset: sqlite3.Row) -> list[tuple[dict, dict, str | None]]:
    """Synthesis and answer cards (from the Flow canvas and chat), oldest first, each with the facts its
    chips name (an answer card's own sheet, or for a synthesis each cited card's fact, TRD §7.4.1) and
    its stale note."""
    from sherlock.stories import service as stories
    from sherlock.stories import trust

    t = trust.Trust(db, dataset)
    dataset_id = dataset["id"]
    out = []
    for r in db.execute("SELECT * FROM cards WHERE dataset_id = ? AND deleted_at IS NULL AND kind IN ('synthesis', 'answer') "
                        "ORDER BY created_at", (dataset_id,)):
        c = stories.to_card(db, r)
        sheet = stories.get_sheet(db, c["fact_sheet_id"])
        if sheet:
            facts = sheet["facts"]
        else:
            keys = [run["key"] for p in (c["headline"], c["body"]) for b in p["blocks"] for run in b["runs"]
                    if run["type"] == "chip" and run.get("key")]
            facts = {k: f for k in keys if (f := stories.fact_for(db, dataset_id, k))}
        out.append((c, facts, stale_note(t.why_not(r), c, dataset["current_version"])))
    return out


def _canvas_notes(db, dataset_id: str) -> list[str]:
    """The canvas's notes in reading order: top to bottom, then left to right (PRD NB-6)."""
    from sherlock.canvas import service as canvas

    doc, _ = canvas.read(db, dataset_id)
    notes = [n for n in doc["nodes"] if not (n.get("sherlock") or {}).get("card_id") and (n.get("text") or "").strip()]
    return [n["text"] for n in sorted(notes, key=lambda n: (round(n["y"] / 40), n["x"]))]


def _helpers_used(db, step_id: str) -> list[str]:
    row = db.execute("SELECT helpers_used_json FROM steps WHERE id = ?", (step_id,)).fetchone()
    return json.loads(row[0]) if row and row[0] else []


def preview(db: sqlite3.Connection, dataset: sqlite3.Row, options: NotebookOptions) -> dict:
    """What the dialog's sentence and notes need (TRD §4.2 preview), without building anything."""
    chain, target, notes = _chain(db, dataset, options)
    rows = _widgets(db, dataset["id"])
    widgets = [w for w in rows if json.loads(w["spec_json"])["op"]["type"] == "sql"]
    runs = [w for w in rows if json.loads(w["spec_json"])["op"]["type"] == "ml" and _finished_run(db, w["run_id"])]
    runs += _extra_runs(db, dataset["id"], rows) if options.include_runs else []
    return {"version": target["version"], "notes": notes,
            "counts": {"steps": len(chain), "widgets": len(widgets) if options.up_to_step is None else 0,
                       "runs": len(runs) if options.up_to_step is None else 0,
                       "cards": len(_cards(db, dataset)) + len(_flow_cards(db, dataset))
                       if options.include_cards and options.up_to_step is None else 0,
                       "notes": len(_canvas_notes(db, dataset["id"])) if options.include_notes else 0}}


def export_path(settings: Settings, dataset: sqlite3.Row, key: str) -> tuple[Path, str]:
    relative = f"exports/notebook_{key}.ipynb"
    return dataset_dir(settings, dataset["user_id"], dataset["id"]) / relative, relative
