"""The notebook eval (`uv run sherlock eval notebook`, TRD §14, PRD NB-3): export each file's notebook
and run it top to bottom in a fresh virtualenv built only from the notebook's requirements cell.

For each file: import it into a throwaway data directory, let the profile job type it, build the
dashboard ("Use as is"), commit two edit batches (cells, a new row, a deleted row) and undo the first
one, which replays the second. Then export the notebook, create a new venv with `uv venv --seed`,
install only the notebook runner (nbclient, ipykernel) into it, and execute the notebook there: its
`%pip install` cell installs the pinned libraries. The rebuilt DataFrame must equal the current
version by `_row_id`, with the same columns, values and dtypes.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
DEFAULT = ["titanic3.csv"]
END_TO_END = ["titanic3.csv", "sales_dated.csv", "wide_messy.csv", "reviews_text.csv"]
RUNNER = r'''
import json, pickle, sys
import nbformat
from nbclient import NotebookClient
from nbformat.v4 import new_code_cell
nb = nbformat.read(sys.argv[1], as_version=4)
nb.cells.append(new_code_cell("import pickle\npickle.dump(df, open('out.pkl', 'wb'))"))
NotebookClient(nb, timeout=900, kernel_name="python3", resources={"metadata": {"path": sys.argv[2]}}).execute()
'''


def _venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _one(name: str, root: Path) -> dict:
    import duckdb
    import pandas as pd
    from fastapi.testclient import TestClient

    from sherlock.config import get_settings
    from sherlock.db.connection import connect
    from sherlock.main import create_app
    from sherlock.storage import dataset_dir, sql_path

    api = "/api/v1"
    started = time.monotonic()
    data = root / "data"
    os.environ["DATA_DIR"] = str(data)
    os.environ["LLM_BASE_URL"] = ""  # the builder's templated fallback: this eval needs no model
    os.environ["DATABASE_URL"] = f"sqlite:///{(data / 'sherlock.db').as_posix()}"
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        with (SAMPLES / name).open("rb") as fh:
            ds = client.post(f"{api}/datasets", files={"file": (name, fh, "text/csv")}).json()
        wait = lambda *s: _wait(lambda: (d := client.get(f"{api}/datasets/{ds['id']}").json())["status"] in s and d)  # noqa: E731
        wait("offer", "failed")
        client.post(f"{api}/datasets/{ds['id']}/use-as-is")
        d = wait("ready")
        page = client.get(f"{api}/datasets/{ds['id']}/rows?limit=3").json()
        col = next(c["name"] for c in page["columns"] if c["name"] not in ("_row_id", "_quarantine_reason"))
        r1, r2 = page["rows"][0]["_row_id"], page["rows"][1]["_row_id"]
        a = client.post(f"{api}/datasets/{ds['id']}/edits", json={
            "base_version": d["current_version"], "edits": [{"row_id": r1, "column": col, "value": "edited"}],
            "new_rows": [{"temp_id": "n", "cells": {col: "new"}}], "deleted_row_ids": [page["rows"][2]["_row_id"]]}).json()
        b = client.post(f"{api}/datasets/{ds['id']}/edits", json={
            "base_version": a["version"], "edits": [{"row_id": r2, "column": col, "value": "kept"}]}).json()
        undo = client.post(f"{api}/datasets/{ds['id']}/steps/{a['step']['id']}/undo",
                           json={"base_version": b["version"], "confirm": True})
        if undo.status_code != 200:
            return {"file": name, "ok": False, "why": undo.json()["error"]["message"]}
        exp = client.post(f"{api}/datasets/{ds['id']}/exports/notebook", json={}).json()
        exp = _wait(lambda: (e := client.get(f"{api}/exports/{exp['export_id']}").json())["status"] in ("done", "failed") and e)
        if exp["status"] != "done":
            return {"file": name, "ok": False, "why": exp["error"]}
        nb_text = client.get(exp["download_url"]).text
        settings = get_settings()
        db = connect(settings)
        user_id, parquet = db.execute(
            "SELECT d.user_id, v.parquet_path FROM datasets d JOIN versions v ON v.dataset_id = d.id "
            "AND v.version = d.current_version WHERE d.id = ?", (ds["id"],)).fetchone()
        db.close()
        folder = dataset_dir(settings, user_id, ds["id"])
        work = root / "run"
        work.mkdir()
        nb_path = work / "export.ipynb"
        nb_path.write_text(nb_text, encoding="utf-8")
        data_file = "".join(json.loads(nb_text)["cells"][1]["source"]).split('DATA_PATH = "')[1].split('"')[0]
        shutil.copyfile(folder / "raw.csv", work / data_file)
        conn = duckdb.connect()
        expected = conn.execute(f"SELECT * FROM read_parquet({sql_path(folder / parquet)}) ORDER BY _row_id").df()
        conn.close()
        counts = exp["counts"]

    venv = root / "venv"
    subprocess.run(["uv", "venv", "--seed", "--python", "3.12", str(venv)], check=True, capture_output=True)
    py = _venv_python(venv)
    subprocess.run(["uv", "pip", "install", "--python", str(py), "nbclient", "ipykernel"], check=True, capture_output=True)
    (root / "runner.py").write_text(RUNNER, encoding="utf-8")
    run = subprocess.run([str(py), str(root / "runner.py"), str(nb_path), str(work)], capture_output=True, text=True)
    if run.returncode != 0:
        tail = (run.stderr or run.stdout).strip().splitlines()[-3:]
        return {"file": name, "ok": False, "why": " / ".join(tail), **counts}
    got = pd.read_pickle(work / "out.pkl").sort_values("_row_id").reset_index(drop=True)
    try:
        pd.testing.assert_frame_equal(got, expected, check_dtype=True)
        ok, why = True, ""
    except AssertionError as exc:
        ok, why = False, str(exc).splitlines()[0]
    return {"file": name, "ok": ok, "why": why, "seconds": round(time.monotonic() - started), **counts}


def _wait(fn, timeout_s: float = 120):
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        value = fn()
        if value:
            return value
        time.sleep(0.5)
    raise SystemExit("timed out")


def run(files: list[str] | None = None) -> str:
    lines = ["| File | Steps | Widgets | Runs in a fresh venv and rebuilds the version | Time |", "|---|---|---|---|---|"]
    for name in files or DEFAULT:
        root = Path(tempfile.mkdtemp(prefix="sherlock-nb-"))
        try:
            r = _one(name, root)
        finally:
            shutil.rmtree(root, ignore_errors=True)
        verdict = "yes" if r["ok"] else f"**no**: {r['why']}"
        lines.append(f"| {r['file']} | {r.get('steps', '–')} | {r.get('widgets', '–')} | {verdict} | {r.get('seconds', '–')} s |")
        sys.stdout.flush()
    return "\n".join(lines)
