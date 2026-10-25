import csv
import io
import json

import pytest

from sherlock.config import get_settings
from sherlock.db.connection import connect
from sherlock.steps.commit import Context, StepSpec, commit_step
from tests.test_steps import sql_step

API = "/api/v1"
CSV = b"name,age,fare,city\nAnn,30,7.25,Paris\nBob,,8.05,Lyon\nCy,41,-1,Paris\nDee,29,100,\n"


@pytest.fixture
def ds(monkeypatch, client):
    monkeypatch.setenv("JOB_WORKERS", "0")
    r = client.post(f"{API}/datasets", files={"file": ("people.csv", CSV, "text/csv")})
    assert r.status_code == 201, r.text
    return r.json()


def rows(client, ds_id, **params):
    r = client.get(f"{API}/datasets/{ds_id}/rows", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def typed_version(app, ds_id):
    """Commit a step that casts age to BIGINT and fare to DOUBLE (what the typing step will do)."""
    db = connect(get_settings())
    ctx = Context(get_settings(), db, app.state.duckdb)
    spec = StepSpec(kind="clean", summary="Typed age and fare", created_by="system",
                    notebook_code="result = df\ndf = result\n", gate="commit")
    step, version = commit_step(ctx, ds_id, 1, spec, sql_step(
        "SELECT * REPLACE (TRY_CAST(age AS BIGINT) AS age, TRY_CAST(fare AS DOUBLE) AS fare) FROM old"))
    db.close()
    return step, version


def test_page_sort_and_filter(client, ds):
    page = rows(client, ds["id"])
    assert page["version"] == 1 and page["total"] == 4
    assert [c["name"] for c in page["columns"]] == ["name", "age", "fare", "city"]
    first = page["rows"][0]
    assert first["_row_id"] == 1 and first["cells"] == {"name": "Ann", "age": "30", "fare": "7.25", "city": "Paris"}
    assert first["marks"] == {} and first["quarantined"] is False

    assert [r["_row_id"] for r in rows(client, ds["id"], sort="name:desc")["rows"]] == [4, 3, 2, 1]
    assert [r["_row_id"] for r in rows(client, ds["id"], offset=1, limit=2)["rows"]] == [2, 3]

    f = json.dumps({"and": [{"col": "city", "op": "eq", "value": "Paris"}]})
    assert rows(client, ds["id"], filter=f)["total"] == 2
    f = json.dumps({"and": [{"col": "city", "op": "empty"}]})
    assert [r["_row_id"] for r in rows(client, ds["id"], filter=f)["rows"]] == [4]
    f = json.dumps({"and": [{"col": "name", "op": "contains", "value": "e"}]})
    assert [r["cells"]["name"] for r in rows(client, ds["id"], filter=f)["rows"]] == ["Dee"]
    f = json.dumps({"and": [{"col": "name", "op": "in", "value": ["Ann", "Cy"]}]})
    assert rows(client, ds["id"], filter=f)["total"] == 2
    assert rows(client, ds["id"], view="missing")["total"] == 2


def test_bad_requests_are_422(client, ds):
    base = f"{API}/datasets/{ds['id']}/rows"
    assert client.get(base, params={"sort": "nope:asc"}).status_code == 422
    assert client.get(base, params={"filter": "{"}).status_code == 422
    assert client.get(base, params={"filter": json.dumps({"and": [{"col": "x", "op": "eq"}]})}).status_code == 422
    assert client.get(base, params={"view": "weird"}).status_code == 422
    assert client.get(base, params={"limit": 501}).status_code == 422
    assert client.get(base, params={"version": 9}).status_code == 404


def test_numeric_filter_uses_the_column_type(app, client, ds):
    typed_version(app, ds["id"])
    f = json.dumps({"and": [{"col": "age", "op": "gte", "value": 30}]})
    page = rows(client, ds["id"], filter=f)
    assert page["version"] == 2 and [r["cells"]["age"] for r in page["rows"]] == [30, 41]
    assert rows(client, ds["id"], sort="fare:desc")["rows"][0]["cells"]["fare"] == 100.0


def test_edit_batch_makes_one_step_with_marks_and_history(app, client, ds):
    _, v = typed_version(app, ds["id"])
    body = {
        "base_version": v,
        "edits": [
            {"row_id": 2, "column": "age", "value": "35"},
            {"row_id": 3, "column": "fare", "value": "abc"},  # invalid for DOUBLE: saved empty, flagged
            {"row_id": 1, "column": "city", "value": "Nice"},
        ],
        "new_rows": [{"temp_id": "t1", "cells": {"name": "Eve", "age": "22"}}],
        "deleted_row_ids": [4],
    }
    r = client.post(f"{API}/datasets/{ds['id']}/edits", json=body)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["version"] == 3 and out["new_row_ids"] == {"t1": 5}
    step = out["step"]
    assert step["kind"] == "edit" and step["created_by"] == "user" and step["gate"] == "user"
    assert step["summary"] == "Edited 3 cells, added 1 row, deleted 1 row by hand"
    assert step["impact"]["rows_added"] == 1 and step["impact"]["rows_deleted"] == 1
    assert "df.loc[df._row_id == 2, 'age'] = 35" in step["notebook_code"]
    assert "df.loc[df._row_id == 3, 'fare'] = None" in step["notebook_code"]

    page = rows(client, ds["id"])
    assert page["version"] == 3 and page["total"] == 4
    by_id = {r["_row_id"]: r for r in page["rows"]}
    assert by_id[2]["cells"]["age"] == 35 and by_id[2]["marks"] == {"age": "changed"}
    assert by_id[3]["cells"]["fare"] is None and by_id[3]["marks"] == {"fare": "invalid"}
    assert by_id[5]["cells"]["name"] == "Eve" and by_id[5]["cells"]["age"] == 22
    assert 4 not in by_id

    history = client.get(f"{API}/datasets/{ds['id']}/cells/3/fare/history").json()["entries"]
    assert history == [{"step_id": step["id"], "step_no": 2, "old": "-1.0", "new": "abc",
                        "summary": step["summary"], "flag": "invalid"}]
    assert rows(client, ds["id"], view="changed")["total"] == 3  # rows 1, 2, 3 (new rows have no cell marks)
    assert rows(client, ds["id"], view="flagged")["total"] == 1

    # Undo drops the marks: they're read through the effective chain.
    r = client.post(f"{API}/datasets/{ds['id']}/steps/{step['id']}/undo", json={"base_version": 3})
    assert r.status_code == 200, r.text
    page = rows(client, ds["id"])
    assert page["version"] == 4 and page["total"] == 4
    assert all(r["marks"] == {} for r in page["rows"])
    assert client.get(f"{API}/datasets/{ds['id']}/cells/3/fare/history").json()["entries"] == []


def test_stale_base_version_lists_conflicts(app, client, ds):
    _, v = typed_version(app, ds["id"])  # v2 changed nothing in name; age 'blank' stays NULL
    ok = client.post(f"{API}/datasets/{ds['id']}/edits", json={
        "base_version": v, "edits": [{"row_id": 1, "column": "name", "value": "Anne"}]})
    assert ok.status_code == 201
    r = client.post(f"{API}/datasets/{ds['id']}/edits", json={
        "base_version": v, "edits": [{"row_id": 1, "column": "name", "value": "Annie"},
                                     {"row_id": 2, "column": "name", "value": "Bobby"}]})
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "conflict" and err["current_version"] == 3
    assert err["conflicts"] == [{"row_id": 1, "column": "name", "mine": "Annie", "theirs": "Anne"}]


def test_integer_edits_are_exact_or_invalid(app, client, ds):
    _, v = typed_version(app, ds["id"])  # age is BIGINT
    r = client.post(f"{API}/datasets/{ds['id']}/edits", json={"base_version": v, "edits": [
        {"row_id": 1, "column": "age", "value": "9007199254740993"},  # 2**53 + 1: a float would round it
        {"row_id": 2, "column": "age", "value": "99999999999999999999"},  # past BIGINT: invalid, not a 500
    ]})
    assert r.status_code == 201, r.text
    assert "df.loc[df._row_id == 1, 'age'] = 9007199254740993" in r.json()["step"]["notebook_code"]
    by_id = {row["_row_id"]: row for row in rows(client, ds["id"])["rows"]}
    assert by_id[1]["cells"]["age"] == 9007199254740993 and by_id[1]["marks"] == {"age": "changed"}
    assert by_id[2]["cells"]["age"] is None and by_id[2]["marks"] == {"age": "invalid"}


def test_edit_validation(client, ds):
    url = f"{API}/datasets/{ds['id']}/edits"
    assert client.post(url, json={"base_version": 1}).status_code == 422
    assert client.post(url, json={"base_version": 1, "edits": [{"row_id": 1, "column": "zzz", "value": "1"}]}).status_code == 422
    assert client.post(url, json={"base_version": 1, "edits": [{"row_id": 99, "column": "name", "value": "1"}]}).status_code == 422
    assert client.post(url, json={"base_version": 1, "deleted_row_ids": [1],
                                  "edits": [{"row_id": 1, "column": "name", "value": "x"}]}).status_code == 422


def test_restore_quarantined_row(app, client, ds):
    db = connect(get_settings())
    ctx = Context(get_settings(), db, app.state.duckdb)
    spec = StepSpec(kind="clean", summary="Quarantined negative fares", created_by="cleaner",
                    notebook_code="result = df\ndf = result\n", gate="flag")
    commit_step(ctx, ds["id"], 1, spec, sql_step(
        "SELECT * REPLACE (CASE WHEN fare LIKE '-%' THEN 'impossible: fare' END AS _quarantine_reason) FROM old"))
    db.close()
    flagged = rows(client, ds["id"], view="flagged")
    assert [(r["_row_id"], r["quarantined"], r["quarantine_reason"]) for r in flagged["rows"]] == [(3, True, "impossible: fare")]
    r = client.post(f"{API}/datasets/{ds['id']}/edits", json={"base_version": 2, "restore_row_ids": [3]})
    assert r.status_code == 201, r.text
    assert r.json()["step"]["summary"] == "Restored 1 row by hand"
    assert rows(client, ds["id"], view="flagged")["total"] == 0


def test_flagged_steps_mark_cells_flagged(app, client, ds):
    db = connect(get_settings())
    ctx = Context(get_settings(), db, app.state.duckdb)
    spec = StepSpec(kind="clean", summary="Filled city", created_by="cleaner",
                    notebook_code="result = df\ndf = result\n", gate="flag")
    commit_step(ctx, ds["id"], 1, spec, sql_step("SELECT * REPLACE (coalesce(city, 'Unknown') AS city) FROM old"))
    db.close()
    row = {r["_row_id"]: r for r in rows(client, ds["id"])["rows"]}[4]
    assert row["marks"] == {"city": "flagged"}


def test_find_values_and_csv_download(client, ds):
    r = client.get(f"{API}/datasets/{ds['id']}/find", params={"q": "par"}).json()
    assert r == {"count": 2, "first_matches": [{"row_id": 1, "column": "city"}, {"row_id": 3, "column": "city"}]}
    r = client.get(f"{API}/datasets/{ds['id']}/find", params={"q": "^[AB]", "regex": True, "column": "name", "all": True}).json()
    assert r["count"] == 2 and r["first_matches"][0] == {"row_id": 1, "column": "name", "value": "Ann"}
    assert client.get(f"{API}/datasets/{ds['id']}/find", params={"q": "(", "regex": True}).status_code == 422
    for q in ("(?=a)", r"(a)\1"):  # valid for Python's `re`, refused by DuckDB's RE2
        assert client.get(f"{API}/datasets/{ds['id']}/find", params={"q": q, "regex": True}).status_code == 422
    assert client.get(f"{API}/datasets/{ds['id']}/find", params={"q": "100%"}).json()["count"] == 0

    download = client.get(f"{API}/datasets/{ds['id']}/export.csv")
    assert download.status_code == 200
    assert download.headers["content-disposition"] == 'attachment; filename="people-v1.csv"'
    lines = list(csv.reader(io.StringIO(download.text)))
    assert lines[0] == ["name", "age", "fare", "city"] and lines[2] == ["Bob", "", "8.05", "Lyon"] and len(lines) == 5


def test_column_values_come_from_the_value_index(client, ds):
    client.get(f"{API}/datasets/{ds['id']}/datacard")  # builds the card and the index
    r = client.get(f"{API}/datasets/{ds['id']}/columns/city/values").json()
    assert r["values"][0] == {"value": "Paris", "count": 2}
    assert client.get(f"{API}/datasets/{ds['id']}/columns/city/values", params={"prefix": "L"}).json()["values"] == [
        {"value": "Lyon", "count": 1}]


def test_rows_of_another_user_are_404(client, ds, app):
    from fastapi.testclient import TestClient
    with TestClient(app) as other:
        assert other.get(f"{API}/datasets/{ds['id']}/rows").status_code == 404
        assert other.post(f"{API}/datasets/{ds['id']}/edits", json={"base_version": 1, "deleted_row_ids": [1]}).status_code == 404
