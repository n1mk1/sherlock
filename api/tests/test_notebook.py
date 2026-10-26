"""Notebook export (TRD §7.7, §14; PRD NB-1–NB-11). The execution test runs the exported notebook
top to bottom with a real kernel (the requirements cell is skipped: this environment already has the
pinned libraries) and checks that it rebuilds the current version exactly, after edits and an undo
with replay, that each widget's table equals the app's widget data, and that each analysis's
reproduction code gives its model card's metrics (within 0.5 points)."""

import json
import math
import shutil
from pathlib import Path

import duckdb
import nbformat
import pandas as pd
import pytest
from nbformat.v4 import new_code_cell

from sherlock.config import get_settings
from sherlock.notebook import scan as scan_mod
from sherlock.notebook.vendored_helpers import helpers_cell
from sherlock.storage import dataset_dir, sql_path
from tests.test_jobs import wait_for, wait_status

API = "/api/v1"


def test_helpers_cell_has_only_the_used_helpers():
    src = helpers_cell(["parse_numbers"])
    assert "def parse_numbers(" in src and "def fill_by_group(" not in src
    assert "def _comma_decimal(" in src  # what parse_numbers needs comes along
    assert "def keep_types(" in src and "def store_step(" in src and "def output_select(" in src
    compile(src, "helpers", "exec")


@pytest.mark.parametrize("code, why", [
    ("import os\n", "imports os"),
    ("df.to_csv('x.csv')\n", "writes a file"),
    ("open('x')\n", "uses open"),
    ("!pip install requests\n", "shell and magic"),
    ("import requests\n", "imports requests"),
])
def test_scan_refuses(code, why):
    nb = nbformat.v4.new_notebook()
    nb.cells.append(new_code_cell(code))
    with pytest.raises(scan_mod.ScanError, match=why):
        scan_mod.scan(nb)


def test_scan_refuses_secrets_and_allows_the_exempt_cells():
    nb = nbformat.v4.new_notebook()
    nb.cells.append(new_code_cell("%pip install -q pandas==2.2.3\n", metadata={"tags": ["requirements"]}))
    nb.cells.append(new_code_cell("from pathlib import Path\nPath('a').write_text('b')\n", metadata={"tags": ["load"]}))
    scan_mod.scan(nb)
    nb.cells.append(nbformat.v4.new_markdown_cell("key LLM_API_KEY=abc"))
    with pytest.raises(scan_mod.ScanError, match="secret"):
        scan_mod.scan(nb)


def test_scan_refuses_a_configured_key_anywhere_in_the_file():
    """A Token Factory key (`v1.…`) doesn't look like `sk-…`, so the scan also looks for the
    configured value itself, in sources, embedded outputs and metadata (PRD NB-11, Rule 6)."""
    key = "v1.CmQKHHN0YXRpY2tleS1leGFtcGxlLW5vdC1yZWFsEiE"
    nb = nbformat.v4.new_notebook()
    nb.cells.append(new_code_cell("x = 1\n"))
    scan_mod.scan(nb, secrets=[key])
    out = nbformat.v4.new_code_cell("result\n")
    out.outputs = [nbformat.v4.new_output("execute_result", data={"text/plain": f"token {key}"}, execution_count=None)]
    nb.cells.append(out)
    with pytest.raises(scan_mod.ScanError, match="API key"):
        scan_mod.scan(nb, secrets=[key])
    nb.cells.pop()
    nb.metadata["note"] = key
    with pytest.raises(scan_mod.ScanError, match="API key"):
        scan_mod.scan(nb, secrets=[key])


def _export(client, ds, **options):
    r = client.post(f"{API}/datasets/{ds}/exports/notebook", json=options)
    assert r.status_code == 201, r.text
    out = r.json()
    if not out["cached"]:
        out = wait_for(lambda: (e := client.get(f"{API}/exports/{out['export_id']}").json())["status"] in ("done", "failed") and e,
                       timeout=60)
    assert out["status"] == "done", out
    return out


def _version_frame(db_path_parts) -> pd.DataFrame:
    path = db_path_parts
    conn = duckdb.connect()
    try:
        return conn.execute(f"SELECT * FROM read_parquet({sql_path(path)}) ORDER BY _row_id").df()
    finally:
        conn.close()


def _norm(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return round(float(v), 6)
    if hasattr(v, "isoformat"):
        return v.isoformat()[:19]
    return str(v)


def execute(nb, workdir: Path, raw: Path, data_file: str) -> tuple[pd.DataFrame, list, list]:
    """Run the notebook with a kernel; returns the final `df`, each widget cell's result rows and
    each run cell's metrics."""
    from nbclient import NotebookClient

    shutil.copyfile(raw, workdir / data_file)
    run = nbformat.from_dict(json.loads(json.dumps(nb)))
    cells = []
    for cell in run.cells:
        if "requirements" in cell.get("metadata", {}).get("tags", []):
            cell.source = "pass  # the test environment has the pinned libraries"
        cells.append(cell)
        if cell.cell_type == "code" and cell.source.startswith("# The dashboard's global filter"):
            cells.append(new_code_cell("_results = globals().get('_results', []) + [result.values.tolist()]"))
        if cell.cell_type == "code" and cell.source.startswith("# Reproduces Sherlock run"):
            cells.append(new_code_cell("_runs = globals().get('_runs', []) + [run_result['metrics']]"))
    cells.append(new_code_cell(
        "import pickle\n"
        "pickle.dump((df, globals().get('_results', []), globals().get('_runs', [])), open('out.pkl', 'wb'))"
    ))
    run.cells = cells
    NotebookClient(run, timeout=180, kernel_name="python3", resources={"metadata": {"path": str(workdir)}}).execute()
    return pd.read_pickle(workdir / "out.pkl")


CLEAN_CODE = (
    "result = df.assign(age=fill_by_group(df, 'age', ['pclass', 'sex']), embarked=normalize_whitespace_case(df['embarked'], 'upper'))\n"
    "result = quarantine_rows(result, result['fare'] > 500, 'fare over 500')"
)


def clean_step(app, ds, version) -> int:
    """A cleaning step committed the way the Cleaner commits one: its code run in the sandbox."""
    from sherlock.db.connection import connect
    from sherlock.sandbox import runner as sandbox
    from sherlock.steps.commit import Context, StepSpec, commit_step

    settings = get_settings()
    db = connect(settings)
    try:
        def produce(old, out):
            r = sandbox.execute(settings, CLEAN_CODE, old, out)
            assert r.ok, r.error
        spec = StepSpec(kind="clean", summary="Filled ages by class and sex", created_by="cleaner", code=CLEAN_CODE,
                        notebook_code=CLEAN_CODE + "\ndf = result\n", gate="commit", confidence=0.9,
                        helpers_used=["fill_by_group", "normalize_whitespace_case", "quarantine_rows"])
        _, new = commit_step(Context(settings, db, app.state.duckdb), ds, version, spec, produce)
        return new
    finally:
        db.close()


@pytest.mark.usefixtures("run_jobs")
def test_export_runs_and_rebuilds_the_version_after_an_undo(client, tmp_path):
    ds = client.post(f"{API}/datasets/sample").json()["id"]
    wait_status(client, ds, "offer")
    client.post(f"{API}/datasets/{ds}/use-as-is")
    wait_status(client, ds, "ready")
    v = client.get(f"{API}/datasets/{ds}").json()["current_version"]
    v = clean_step(client.app, ds, v)
    a = client.post(f"{API}/datasets/{ds}/edits", json={
        "base_version": v, "edits": [{"row_id": 1, "column": "age", "value": "33"},
                                     {"row_id": 2, "column": "fare", "value": "abc"},
                                     {"row_id": 3, "column": "name", "value": "O'Brien, \"Q\""}],
        "new_rows": [{"temp_id": "n", "cells": {"name": "New", "age": "40", "survived": "1"}}],
        "deleted_row_ids": [5]}).json()
    b = client.post(f"{API}/datasets/{ds}/edits", json={
        "base_version": a["version"], "edits": [{"row_id": 4, "column": "embarked", "value": "Q"}]}).json()
    undone = client.post(f"{API}/datasets/{ds}/steps/{a['step']['id']}/undo",
                         json={"base_version": b["version"], "confirm": True})
    assert undone.status_code == 200, undone.text

    # The cascade and the stories job change the dataset's state; export once they're done.
    wait_for(lambda: all(j["status"] in ("done", "failed", "cancelled") for j in client.get(f"{API}/jobs?dataset_id={ds}").json()),
             timeout=60)
    pre = client.get(f"{API}/datasets/{ds}/exports/notebook/preview").json()
    assert pre["counts"]["steps"] == 3 and pre["options"]["include_data"] is True
    out = _export(client, ds)
    again = client.post(f"{API}/datasets/{ds}/exports/notebook", json={}).json()
    assert again["cached"] and again["export_id"] == out["export_id"]

    r = client.get(out["download_url"])
    assert r.status_code == 200
    assert 'filename="titanic3-v' in r.headers["content-disposition"]
    nb = nbformat.reads(r.text, as_version=4)
    nbformat.validate(nb)
    text = "\n".join(c.source for c in nb.cells)
    assert "Step 2 was undone" not in text or "isn't replayed" in text
    assert "was undone" in text

    settings = get_settings()
    dataset = client.get(f"{API}/datasets/{ds}").json()
    from sherlock.db.connection import connect
    db = connect(settings)
    user_id, parquet = db.execute(
        "SELECT d.user_id, v.parquet_path FROM datasets d JOIN versions v ON v.dataset_id = d.id AND v.version = d.current_version "
        "WHERE d.id = ?", (ds,)).fetchone()
    db.close()
    folder = dataset_dir(settings, user_id, ds)
    work = tmp_path / "run"
    work.mkdir()
    df, results, runs = execute(nb, work, folder / "raw.csv", "titanic3-raw.csv")

    expected = _version_frame(folder / parquet)
    got = df.sort_values("_row_id").reset_index(drop=True)
    assert list(got.columns) == list(expected.columns)
    pd.testing.assert_frame_equal(got, expected, check_dtype=True)
    assert dataset["current_version"] == undone.json()["version"]

    widgets = client.get(f"{API}/datasets/{ds}/widgets").json()["widgets"]
    order = {it["i"]: (it["y"], it["x"]) for it in client.get(f"{API}/datasets/{ds}/widgets").json()["layout"]["lg"]}
    widgets = sorted(widgets, key=lambda w: order.get(w["id"], (10**9, 0)))
    analyses = [w for w in widgets if w["spec"]["op"]["type"] == "ml"]  # emitted via their runs (TRD §7.7)
    widgets = [w for w in widgets if w not in analyses]
    assert len(results) == len(widgets) > 0
    assert len(runs) == len(analyses) == 1 and pre["counts"]["runs"] == 1
    for w, metrics in zip(analyses, runs):  # PRD NB-5: the notebook reproduces each run's metrics
        card = client.get(f"{API}/runs/{w['run_id']}/model-card").json()
        assert metrics["metric"] == card["model"]["metric"]
        assert abs(metrics["value"] - card["model"]["value"]) <= 0.005, (metrics, card["model"])
        assert "# Reproduces Sherlock run" in text and card["verdict_text"] in text
    for w, rows in zip(widgets, results):
        app_rows = client.get(f"{API}/widgets/{w['id']}/data").json()["rows"]
        assert [[_norm(v) for v in r] for r in rows] == [[_norm(v) for v in r] for r in app_rows], w["title"]


@pytest.mark.usefixtures("run_jobs")
def test_a_ragged_file_rebuilds_in_the_notebook(client, tmp_path):
    # Review Day 2 H1: a row with an extra field is read with explicit columns and quarantined at
    # import; the notebook's load cell does the same, so it rebuilds the version exactly.
    lines = ["a,b,c"] + [f"{i},x{i},{i * 2}" for i in range(60)]
    content = ("\n".join(lines[:31] + ["30,extra,1,TOO"] + lines[31:]) + "\n").encode()
    ds = client.post(f"{API}/datasets", files={"file": ("ragged.csv", content, "text/csv")}).json()["id"]
    wait_status(client, ds, "offer")
    client.post(f"{API}/datasets/{ds}/use-as-is")
    wait_status(client, ds, "ready")
    wait_for(lambda: all(j["status"] in ("done", "failed", "cancelled") for j in client.get(f"{API}/jobs?dataset_id={ds}").json()),
             timeout=60)
    nb = nbformat.reads(client.get(_export(client, ds)["download_url"]).text, as_version=4)
    load = next(c.source for c in nb.cells if "load" in c.get("metadata", {}).get("tags", []))
    assert "auto_detect=false" in load and "extra fields" in load

    from sherlock.db.connection import connect
    settings = get_settings()
    db = connect(settings)
    user_id, parquet = db.execute(
        "SELECT d.user_id, v.parquet_path FROM datasets d JOIN versions v ON v.dataset_id = d.id AND v.version = d.current_version "
        "WHERE d.id = ?", (ds,)).fetchone()
    db.close()
    folder = dataset_dir(settings, user_id, ds)
    data_file = "".join(nb.cells[1].source).split('DATA_PATH = "')[1].split('"')[0]
    work = tmp_path / "run"
    work.mkdir()
    df, _, _ = execute(nb, work, folder / "raw.csv", data_file)
    expected = _version_frame(folder / parquet)
    pd.testing.assert_frame_equal(df.sort_values("_row_id").reset_index(drop=True), expected, check_dtype=True)
    assert expected["_quarantine_reason"].notna().sum() == 1


@pytest.mark.usefixtures("run_jobs")
def test_one_broken_widget_or_an_update_never_spoils_an_export(client, monkeypatch):
    """Plan 1.4: a widget whose query fails on the version gets a Markdown cell saying why and the export
    still succeeds; deleting a card gives the export a new cache key; an export while the cards are being
    updated waits for them, or says so in its first cell."""
    import threading
    import time

    from sherlock.db.connection import connect
    from sherlock.db.util import new_id, now_iso
    from sherlock.jobs import export as export_job

    ds = client.post(f"{API}/datasets/sample").json()["id"]
    wait_status(client, ds, "offer")
    client.post(f"{API}/datasets/{ds}/use-as-is")
    wait_status(client, ds, "ready")
    wait_for(lambda: all(j["status"] in ("done", "failed", "cancelled")
                         for j in client.get(f"{API}/jobs?dataset_id={ds}").json()), timeout=120)
    widgets = client.get(f"{API}/datasets/{ds}/widgets").json()["widgets"]
    sql_widgets = [w for w in widgets if w["spec"]["op"]["type"] == "sql"]
    broken = sql_widgets[0]
    db = connect(client.app.state.settings)
    try:
        spec = {**broken["spec"], "op": {"type": "sql", "sql": 'SELECT "no_such_column" FROM t WHERE {{rows}}'}}
        db.execute("UPDATE widgets SET spec_json = ? WHERE id = ?", (json.dumps(spec), broken["id"]))
        user_id = db.execute("SELECT user_id FROM datasets WHERE id = ?", (ds,)).fetchone()[0]
    finally:
        db.close()
    out = _export(client, ds)
    nb = nbformat.reads(client.get(out["download_url"]).text, as_version=4)
    md = [c.source for c in nb.cells if c.cell_type == "markdown"]
    assert any(m.startswith(f"## {broken['title']}") and "This widget fails on version" in m for m in md)
    assert "1 widget failed on version" in nb.cells[0].source
    assert out["counts"]["widgets"] == len(sql_widgets) - 1

    # A deleted card changes the dataset's state, so the next export isn't the cached one.
    same = client.post(f"{API}/datasets/{ds}/exports/notebook", json={}).json()
    assert same["cached"] and same["export_id"] == out["export_id"]
    card = client.get(f"{API}/datasets/{ds}/cards").json()[0]
    assert client.delete(f"{API}/cards/{card['id']}").status_code == 204
    fresh = _export(client, ds)
    assert not fresh["cached"] and fresh["export_id"] != out["export_id"]

    def updating_job(status="running"):
        db = connect(client.app.state.settings)
        try:
            jid = new_id("job")
            db.execute("INSERT INTO jobs (id, dataset_id, user_id, kind, status, params_json, owner_pid, created_at) "
                       "VALUES (?, ?, ?, 'cascade', ?, '{}', 'elsewhere:1:x', ?)", (jid, ds, user_id, status, now_iso()))
            db.execute("UPDATE datasets SET state_rev = state_rev + 1 WHERE id = ?", (ds,))  # as a cascade's start does
            return jid
        finally:
            db.close()

    def finish(jid):
        db = connect(client.app.state.settings)
        try:
            db.execute("UPDATE jobs SET status = 'done', finished_at = ? WHERE id = ?", (now_iso(), jid))
        finally:
            db.close()

    # A cascade still running after the wait: the notebook says the cards were being updated.
    monkeypatch.setattr(export_job, "WAIT_S", 0.5)
    stuck = updating_job()
    out = _export(client, ds)
    first = nbformat.reads(client.get(out["download_url"]).text, as_version=4).cells[0].source
    assert "Story cards were still being updated when this was exported" in first
    finish(stuck)

    # One that ends within the wait: the export waits for it and needs no note.
    monkeypatch.setattr(export_job, "WAIT_S", 20.0)
    soon = updating_job()
    threading.Thread(target=lambda: (time.sleep(1.0), finish(soon))).start()
    started = time.monotonic()
    out = _export(client, ds)
    assert time.monotonic() - started >= 0.9
    first = nbformat.reads(client.get(out["download_url"]).text, as_version=4).cells[0].source
    assert "still being updated" not in first
