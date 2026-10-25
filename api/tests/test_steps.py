import json
import threading
from pathlib import Path

import duckdb
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from sherlock.config import get_settings
from sherlock.db.connection import connect
from sherlock.errors import ApiError
from sherlock.steps.commit import Context, StepSpec, commit_step
from sherlock.steps.notebook import render_edit_batch, typed
from sherlock.storage import sql_path

API = "/api/v1"
FILL_CODE = "result = df.assign(age=df['age'].fillna('30'))\ndf = result\n"


def sql_step(select: str):
    """A `produce` function: `select` reads the current version as `old`."""
    def produce(old: Path, out: Path) -> None:
        conn = duckdb.connect()
        conn.execute(f"CREATE VIEW old AS SELECT * FROM read_parquet({sql_path(old)})")
        conn.execute(f"COPY ({select}) TO {sql_path(out)} (FORMAT PARQUET)")
        conn.close()
    return produce


@pytest.fixture
def setup(app, client):
    ds = client.post(f"{API}/datasets/sample").json()
    db = connect(get_settings())
    ctx = Context(get_settings(), db, app.state.duckdb)
    yield ctx, ds["id"], client
    db.close()


def fill_age(ctx, dataset_id, base=1, **overrides):
    spec = StepSpec(kind="clean", summary="Filled missing ages with 30", created_by="cleaner",
                    notebook_code=FILL_CODE, code="result = ...", **overrides)
    return commit_step(ctx, dataset_id, base, spec, sql_step("SELECT * REPLACE (coalesce(age, '30') AS age) FROM old"))


def scalar(ctx, sql, *params):
    return ctx.db.execute(sql, params).fetchone()[0]


# --- commit_step ----------------------------------------------------------------------


def test_commit_makes_a_new_version_with_lineage(setup):
    ctx, ds, client = setup
    step, version = fill_age(ctx, ds)
    assert version == 2
    assert (step["no"], step["kind"], step["from_version"], step["to_version"]) == (1, "clean", 1, 2)
    assert step["column_targets"] == ["age"]
    impact = step["impact"]
    assert (impact["rows_in"], impact["rows_out"], impact["cells_changed"], impact["quarantined"]) == (1309, 1309, 263, 0)
    assert impact["before_after"][0] == {"row_id": impact["before_after"][0]["row_id"], "column": "age", "old": None, "new": "30"}

    dataset = ctx.db.execute("SELECT * FROM datasets WHERE id = ?", (ds,)).fetchone()
    assert (dataset["current_version"], dataset["state_rev"]) == (2, 1)
    v2 = ctx.db.execute("SELECT * FROM versions WHERE dataset_id = ? AND version = 2", (ds,)).fetchone()
    assert v2["parquet_path"] == "versions/v2.parquet" and json.loads(v2["effective_step_ids_json"]) == [step["id"]]
    assert scalar(ctx, "SELECT count(*) FROM lineage WHERE step_id = ? AND column = 'age' AND old_value IS NULL", step["id"]) == 263

    # Re-profiled: the new version's card has no missing ages; version 1's card is unchanged.
    card = client.get(f"{API}/datasets/{ds}/datacard").json()
    assert card["version"] == 2
    assert {c["name"]: c["missing"] for c in card["columns"]}["age"] == 0
    assert {c["name"]: c["missing"] for c in client.get(f"{API}/datasets/{ds}/datacard?version=1").json()["columns"]}["age"] == 263


def test_stale_base_version_is_a_conflict(setup):
    ctx, ds, client = setup
    fill_age(ctx, ds)
    with pytest.raises(ApiError) as err:
        fill_age(ctx, ds, base=1)
    assert err.value.status == 409 and err.value.extra == {"current_version": 2}
    assert scalar(ctx, "SELECT count(*) FROM versions WHERE dataset_id = ?", ds) == 2


def test_cleaning_may_not_drop_rows_and_nothing_is_written(setup):
    ctx, ds, client = setup
    spec = StepSpec(kind="clean", summary="drop", created_by="cleaner", notebook_code="result = df.head()\ndf = result")
    with pytest.raises(ValueError, match="quarantine"):
        commit_step(ctx, ds, 1, spec, sql_step("SELECT * FROM old WHERE _row_id > 5"))
    assert scalar(ctx, "SELECT current_version FROM datasets WHERE id = ?", ds) == 1
    assert scalar(ctx, "SELECT count(*) FROM steps WHERE dataset_id = ?", ds) == 0
    user = client.get(f"{API}/me").json()["user_id"]
    assert not (get_settings().data_dir / "users" / user / "datasets" / ds / "versions" / "v2.parquet").exists()


@pytest.mark.parametrize("kind,code,message", [
    ("clean", "", "required"),
    ("clean", "result = df", "df = result"),
    ("undo", "# x", "undo"),
])
def test_step_spec_checks(setup, kind, code, message):
    ctx, ds, _ = setup
    spec = StepSpec(kind=kind, summary="x", created_by="cleaner", notebook_code=code)
    with pytest.raises(ValueError, match=message):
        commit_step(ctx, ds, 1, spec, sql_step("SELECT * FROM old"))


def test_row_id_must_stay_unique(setup):
    ctx, ds, _ = setup
    spec = StepSpec(kind="edit", summary="x", created_by="user", notebook_code="# x")
    with pytest.raises(ValueError, match="unique"):
        commit_step(ctx, ds, 1, spec, sql_step("SELECT * FROM old UNION ALL SELECT * FROM old WHERE _row_id = 1"))


def test_quarantine_and_retype_lineage(setup):
    ctx, ds, _ = setup
    spec = StepSpec(kind="clean", summary="Typed pclass; quarantined fare-less rows", created_by="system",
                    notebook_code="result = df\ndf = result", code="SELECT ...")
    step, _ = commit_step(ctx, ds, 1, spec, sql_step(
        "SELECT * REPLACE (CAST(pclass AS BIGINT) AS pclass, "
        "CASE WHEN fare IS NULL THEN 'type: fare' ELSE _quarantine_reason END AS _quarantine_reason) FROM old"))
    assert step["impact"]["cells_changed"] == 0  # '1' → 1 is a retype, not a change
    assert step["impact"]["quarantined"] == 1
    assert scalar(ctx, "SELECT count(*) FROM lineage WHERE step_id = ? AND column = '_row' AND flag = 'quarantined'", step["id"]) == 1


def test_edit_batch_lineage_new_rows_and_user_edited_cells(setup):
    ctx, ds, _ = setup
    edits = [{"row_id": 1, "column": "age", "value": "29.5"}]
    new_rows = [{"row_id": 1310, "cells": {"name": "New Passenger", "age": "40"}}]
    code = render_edit_batch(edits, new_rows, [2], [], {"age": "VARCHAR", "name": "VARCHAR"})
    spec = StepSpec(kind="edit", summary="Edited 1 cell, added 1 row, deleted 1 row", created_by="user",
                    notebook_code=code, edits={"edits": edits, "new_rows": new_rows, "deleted_row_ids": [2]})
    step, version = commit_step(ctx, ds, 1, spec, sql_step(
        "SELECT * REPLACE (CASE WHEN _row_id = 1 THEN '29.5' ELSE age END AS age) FROM old WHERE _row_id != 2 "
        "UNION ALL BY NAME SELECT 1310::BIGINT AS _row_id, NULL::VARCHAR AS _quarantine_reason, "
        "'New Passenger' AS name, '40' AS age"))
    impact = step["impact"]
    assert (impact["rows_added"], impact["rows_deleted"], impact["cells_changed"]) == (1, 1, 1)
    assert scalar(ctx, "SELECT next_row_id FROM datasets WHERE id = ?", ds) == 1311
    assert [tuple(r) for r in ctx.db.execute("SELECT row_id, column FROM user_edited_cells WHERE dataset_id = ?", (ds,))] == [(1, "age")]
    rows = {r[0]: r[1] for r in ctx.db.execute("SELECT row_id, new_value FROM lineage WHERE step_id = ? AND column = '_row'", (step["id"],))}
    assert rows == {1310: "added", 2: "deleted"}
    assert step["edits"]["deleted_row_ids"] == [2]


def test_deleted_row_ids_are_never_reused(setup):
    ctx, ds, _ = setup
    spec = StepSpec(kind="edit", summary="x", created_by="user", notebook_code="# x")
    commit_step(ctx, ds, 1, spec, sql_step("SELECT * FROM old WHERE _row_id != 5"))
    with pytest.raises(ValueError, match="fresh"):
        commit_step(ctx, ds, 2, spec, sql_step("SELECT * FROM old UNION ALL BY NAME SELECT 5::BIGINT AS _row_id"))


def test_concurrent_commits_one_wins(setup):
    ctx, ds, _ = setup
    results = []

    def worker():
        db = connect(get_settings())
        try:
            fill_age(Context(ctx.settings, db, ctx.cache), ds)
            results.append("ok")
        except ApiError as exc:
            results.append(exc.status)
        finally:
            db.close()

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results, key=str) == [409, 409, "ok"]


# --- notebook code for edit batches ---------------------------------------------------


def test_rendered_edit_batch_reproduces_the_edit():
    df = pd.DataFrame({"_row_id": [1, 2, 3], "_quarantine_reason": [None, "type: age", None],
                       "age": [30, None, 41], "city": ["Oslo", "Rome", "Lima"]})
    code = render_edit_batch(
        edits=[{"row_id": 1, "column": "age", "value": "31"}, {"row_id": 3, "column": "city", "value": "Quito"}],
        new_rows=[{"row_id": 4, "cells": {"age": "22", "city": "Kyiv"}}],
        deleted_row_ids=[3],
        restore_row_ids=[2],
        dtypes={"age": "BIGINT", "city": "VARCHAR"},
    )
    assert "df.loc[df._row_id == 1, 'age'] = 31" in code
    scope = {"df": df.copy(), "pd": pd}
    exec(code, scope)
    out = scope["df"].set_index("_row_id")
    assert list(out.index) == [1, 2, 4]
    assert out.loc[1, "age"] == 31 and out.loc[4, "city"] == "Kyiv"
    assert out.loc[2, "_quarantine_reason"] is None


def test_typed_values():
    assert typed("3", "BIGINT") == 3 and typed("3.5", "DOUBLE") == 3.5
    assert typed("yes", "BOOLEAN") is True and typed(None, "VARCHAR") is None
    assert typed("2026-01-02", "DATE") == pd.Timestamp("2026-01-02")
    assert typed("abc", "BIGINT") == "abc"  # an invalid value stays text; the commit's checks catch it


# --- endpoints and undo ---------------------------------------------------------------


def test_steps_endpoints(setup):
    ctx, ds, client = setup
    first, _ = fill_age(ctx, ds)
    steps = client.get(f"{API}/datasets/{ds}/steps").json()
    assert [(s["no"], s["active"]) for s in steps] == [(1, True)]
    one = client.get(f"{API}/datasets/{ds}/steps/{first['id']}").json()
    assert one["notebook_code"] == FILL_CODE and one["impact"]["cells_changed"] == 263
    assert client.get(f"{API}/datasets/{ds}/steps/stp_nope").status_code == 404


def test_undo_latest_points_back_at_the_old_data(setup):
    ctx, ds, client = setup
    step, _ = fill_age(ctx, ds)

    stale = client.post(f"{API}/datasets/{ds}/steps/{step['id']}/undo", json={"base_version": 1})
    assert stale.status_code == 409 and stale.json()["error"]["current_version"] == 2

    res = client.post(f"{API}/datasets/{ds}/steps/{step['id']}/undo", json={"base_version": 2})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["version"] == 3
    assert (body["step"]["kind"], body["step"]["undone_step_id"], body["step"]["no"]) == ("undo", step["id"], 2)
    assert body["step"]["impact"]["cells_changed"] == 263

    v3 = ctx.db.execute("SELECT * FROM versions WHERE dataset_id = ? AND version = 3", (ds,)).fetchone()
    assert v3["parquet_path"] == "versions/v1.parquet"  # no data rewritten
    assert json.loads(v3["effective_step_ids_json"]) == []
    assert [(s["no"], s["kind"], s["active"]) for s in client.get(f"{API}/datasets/{ds}/steps").json()] == [
        (2, "undo", False), (1, "clean", False)]
    card = client.get(f"{API}/datasets/{ds}/datacard").json()
    assert card["version"] == 3 and {c["name"]: c["missing"] for c in card["columns"]}["age"] == 263

    again = client.post(f"{API}/datasets/{ds}/steps/{step['id']}/undo", json={"base_version": 3})
    assert again.status_code == 409
    undo_of_undo = client.post(f"{API}/datasets/{ds}/steps/{body['step']['id']}/undo", json={"base_version": 3})
    assert undo_of_undo.status_code == 409


def test_undo_clears_user_edited_cells(setup):
    ctx, ds, client = setup
    spec = StepSpec(kind="edit", summary="Edited 1 cell", created_by="user",
                    notebook_code=render_edit_batch([{"row_id": 1, "column": "age", "value": "5"}], [], [], [], {}))
    step, _ = commit_step(ctx, ds, 1, spec, sql_step("SELECT * REPLACE (CASE WHEN _row_id = 1 THEN '5' ELSE age END AS age) FROM old"))
    assert scalar(ctx, "SELECT count(*) FROM user_edited_cells WHERE dataset_id = ?", ds) == 1
    assert client.post(f"{API}/datasets/{ds}/steps/{step['id']}/undo", json={"base_version": 2}).status_code == 200
    assert scalar(ctx, "SELECT count(*) FROM user_edited_cells WHERE dataset_id = ?", ds) == 0


def test_undo_of_an_earlier_step_needs_replay(setup):
    ctx, ds, client = setup
    first, _ = fill_age(ctx, ds)
    spec = StepSpec(kind="clean", summary="Trimmed names", created_by="cleaner", notebook_code="result = df\ndf = result")
    commit_step(ctx, ds, 2, spec, sql_step("SELECT * REPLACE (trim(name) AS name) FROM old"))
    ask = client.post(f"{API}/datasets/{ds}/steps/{first['id']}/undo", json={"base_version": 3}).json()
    assert ask == {"confirm_required": True, "replay_needed": [2], "warning": None}
    confirmed = client.post(f"{API}/datasets/{ds}/steps/{first['id']}/undo", json={"base_version": 3, "confirm": True})
    assert confirmed.status_code == 409 and confirmed.json()["error"]["replay_needed"] == [2]


def test_undo_of_the_typing_step_warns_first(setup):
    ctx, ds, client = setup
    spec = StepSpec(kind="clean", summary="Typed columns", created_by="system", notebook_code="result = df\ndf = result")
    step, _ = commit_step(ctx, ds, 1, spec, sql_step("SELECT * REPLACE (CAST(pclass AS BIGINT) AS pclass) FROM old"))
    ask = client.post(f"{API}/datasets/{ds}/steps/{step['id']}/undo", json={"base_version": 2}).json()
    assert ask == {"confirm_required": True, "replay_needed": [], "warning": "typing"}
    done = client.post(f"{API}/datasets/{ds}/steps/{step['id']}/undo", json={"base_version": 2, "confirm": True})
    assert done.status_code == 200 and done.json()["version"] == 3


def test_other_users_cannot_see_steps(app, setup):
    ctx, ds, _ = setup
    fill_age(ctx, ds)
    with TestClient(app) as bob:
        assert bob.get(f"{API}/datasets/{ds}/steps").status_code == 404
        assert bob.post(f"{API}/datasets/{ds}/steps/x/undo", json={"base_version": 2}).status_code == 404


def test_commit_and_undo_emit_version_created(setup, app):
    ctx, ds, client = setup
    ctx.bus = app.state.bus
    step, _ = fill_age(ctx, ds)
    r = client.post(f"{API}/datasets/{ds}/steps/{step['id']}/undo", json={"base_version": 2, "confirm": True})
    assert r.status_code == 200, r.text
    rows = ctx.db.execute(
        "SELECT data_json FROM job_events WHERE dataset_id = ? AND type = 'version.created' ORDER BY id", (ds,)
    ).fetchall()
    created = [json.loads(row[0]) for row in rows]
    assert [(c["version"], c["step_id"]) for c in created] == [(2, step["id"]), (3, r.json()["step"]["id"])]
    assert created[0] == {"dataset_id": ds, "version": 2, "step_id": step["id"], "summary": "Filled missing ages with 30",
                          "cells_changed": 263, "rows_added": 0, "rows_removed": 0}
