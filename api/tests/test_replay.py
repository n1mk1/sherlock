"""Undo with replay (TRD §7.8, Implementation Plan D5.5): undoing an earlier step re-applies the
later steps on the data before it; a replay that can't apply changes nothing."""

import json

import duckdb
import pytest

from sherlock.config import get_settings
from sherlock.db.connection import connect
from sherlock.steps.commit import Context
from sherlock.storage import dataset_dir, sql_path

API = "/api/v1"


@pytest.fixture
def ds(app, client):
    d = client.post(f"{API}/datasets/sample").json()
    db = connect(get_settings())
    yield d["id"], client, db
    db.close()


def edit(client, ds, base, **batch):
    r = client.post(f"{API}/datasets/{ds}/edits", json={"base_version": base, **batch})
    assert r.status_code == 201, r.text
    return r.json()


def undo(client, ds, step_id, base, confirm=True):
    return client.post(f"{API}/datasets/{ds}/steps/{step_id}/undo", json={"base_version": base, "confirm": confirm})


def cells(db, ds, *row_ids, column="age"):
    v = db.execute("SELECT d.user_id, v.parquet_path FROM versions v JOIN datasets d ON d.id = v.dataset_id "
                   "AND v.version = d.current_version WHERE d.id = ?", (ds,)).fetchone()
    path = dataset_dir(get_settings(), v[0], ds) / v[1]
    conn = duckdb.connect()
    try:
        rows = conn.execute(f'SELECT _row_id, "{column}" FROM read_parquet({sql_path(path)}) '
                            f"WHERE list_contains(?, _row_id) ORDER BY 1", [list(row_ids)]).fetchall()
        return dict(rows)
    finally:
        conn.close()


def test_undo_an_earlier_edit_keeps_the_later_one(ds):
    d, client, db = ds
    before = cells(db, d, 1, 2)
    a = edit(client, d, 1, edits=[{"row_id": 1, "column": "age", "value": "5"}])
    b = edit(client, d, 2, edits=[{"row_id": 2, "column": "age", "value": "6"}])
    assert undo(client, d, a["step"]["id"], 3, confirm=False).json()["replay_needed"] == [b["step"]["no"]]
    r = undo(client, d, a["step"]["id"], 3)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == 4 and body["step"]["replayed_step_ids"] == [b["step"]["id"]]
    assert cells(db, d, 1, 2) == {1: before[1], 2: "6"}
    v4 = db.execute("SELECT * FROM versions WHERE dataset_id = ? AND version = 4", (d,)).fetchone()
    assert json.loads(v4["effective_step_ids_json"]) == [b["step"]["id"]]
    assert v4["parquet_path"] == "versions/v4.parquet"
    # Marks and history follow the replayed data: row 2 is still marked, row 1 isn't.
    page = client.get(f"{API}/datasets/{d}/rows?limit=3").json()
    marks = {r["_row_id"]: r["marks"] for r in page["rows"]}
    assert marks[1] == {} and marks[2] == {"age": "changed"}
    edited = db.execute("SELECT row_id, step_id FROM user_edited_cells WHERE dataset_id = ?", (d,)).fetchall()
    assert [tuple(e) for e in edited] == [(2, b["step"]["id"])]


def test_undo_the_latest_step_points_back_when_a_version_matches(ds):
    d, client, db = ds
    a = edit(client, d, 1, edits=[{"row_id": 1, "column": "age", "value": "5"}])
    b = edit(client, d, 2, edits=[{"row_id": 2, "column": "age", "value": "6"}])
    c = edit(client, d, 3, edits=[{"row_id": 3, "column": "age", "value": "7"}])
    assert undo(client, d, b["step"]["id"], 4).status_code == 200  # v5: [a, c] by replay
    r = undo(client, d, c["step"]["id"], 5)                         # [a] is v2: no replay, no new file
    assert r.status_code == 200 and r.json()["step"]["replayed_step_ids"] is None
    assert db.execute("SELECT parquet_path FROM versions WHERE dataset_id = ? AND version = 6", (d,)).fetchone()[0] \
        == "versions/v2.parquet"
    assert cells(db, d, 1)[1] == "5" and a["version"] == 2


def test_rebuild_when_no_version_has_the_prefix(ds):
    d, client, db = ds
    a = edit(client, d, 1, edits=[{"row_id": 1, "column": "age", "value": "5"}])
    b = edit(client, d, 2, edits=[{"row_id": 2, "column": "age", "value": "6"}])
    c = edit(client, d, 3, edits=[{"row_id": 3, "column": "age", "value": "7"}])
    e = edit(client, d, 4, edits=[{"row_id": 4, "column": "age", "value": "8"}])
    assert undo(client, d, b["step"]["id"], 5).status_code == 200    # v6: [a, c', e']
    r = undo(client, d, e["step"]["id"], 6)                          # [a, c] exists nowhere: rebuilt from [a]
    assert r.status_code == 200, r.text
    assert r.json()["step"]["replayed_step_ids"] == [c["step"]["id"]]
    got = cells(db, d, 1, 2, 3, 4)
    assert (got[1], got[3]) == ("5", "7") and got[2] != "6" and got[4] != "8"


def test_a_replay_that_cannot_apply_changes_nothing(ds):
    d, client, db = ds
    added = edit(client, d, 1, new_rows=[{"temp_id": "n1", "cells": {"name": "New person"}}])
    new_id = added["new_row_ids"]["n1"]
    later = edit(client, d, 2, edits=[{"row_id": new_id, "column": "age", "value": "40"}])
    r = undo(client, d, added["step"]["id"], 3)
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["failed_step_id"] == later["step"]["id"] and "no longer exists" in err["reason"]
    assert db.execute("SELECT current_version FROM datasets WHERE id = ?", (d,)).fetchone()[0] == 3
    assert db.execute("SELECT count(*) FROM steps WHERE dataset_id = ? AND kind = 'undo'", (d,)).fetchone()[0] == 0


def test_replay_reruns_cleaning_code_in_the_sandbox(app, ds):
    d, client, db = ds
    from sherlock.steps.commit import StepSpec, commit_step
    from tests.test_steps import sql_step

    ctx = Context(get_settings(), db, app.state.duckdb)
    a = edit(client, d, 1, edits=[{"row_id": 1, "column": "name", "value": "Someone"}])
    spec = StepSpec(kind="clean", summary="Upper-cased names", created_by="cleaner",
                    notebook_code="result = df.assign(name=df['name'].str.upper())\ndf = result\n")
    commit_step(ctx, d, 2, spec, sql_step("SELECT * REPLACE (upper(name) AS name) FROM old"))
    assert cells(db, d, 1, column="name") == {1: "SOMEONE"}
    r = undo(client, d, a["step"]["id"], 3)
    assert r.status_code == 200, r.text
    assert cells(db, d, 1, column="name")[1] == cells(db, d, 1, column="name")[1].upper() != "SOMEONE"
