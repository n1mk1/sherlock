"""Notebook export (TRD §7.7, §14; PRD NB-1–NB-11). The execution test runs the exported notebook
top to bottom with a real kernel (the requirements cell is skipped: this environment already has the
pinned libraries) and checks that it rebuilds the current version exactly, after edits and an undo
with replay, and that each widget's table equals the app's widget data."""

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


def execute(nb, workdir: Path, raw: Path, data_file: str) -> tuple[pd.DataFrame, list]:
    """Run the notebook with a kernel; returns the final `df` and each widget cell's result rows."""
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
    cells.append(new_code_cell(
        "import pickle\n"
        "pickle.dump((df, globals().get('_results', [])), open('out.pkl', 'wb'))"
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
    df, results = execute(nb, work, folder / "raw.csv", "titanic3-raw.csv")

    expected = _version_frame(folder / parquet)
    got = df.sort_values("_row_id").reset_index(drop=True)
    assert list(got.columns) == list(expected.columns)
    pd.testing.assert_frame_equal(got, expected, check_dtype=True)
    assert dataset["current_version"] == undone.json()["version"]

    widgets = client.get(f"{API}/datasets/{ds}/widgets").json()["widgets"]
    order = {it["i"]: (it["y"], it["x"]) for it in client.get(f"{API}/datasets/{ds}/widgets").json()["layout"]["lg"]}
    widgets = sorted(widgets, key=lambda w: order.get(w["id"], (10**9, 0)))
    assert len(results) == len(widgets) > 0
    for w, rows in zip(widgets, results):
        app_rows = client.get(f"{API}/widgets/{w['id']}/data").json()["rows"]
        assert [[_norm(v) for v in r] for r in rows] == [[_norm(v) for v in r] for r in app_rows], w["title"]
