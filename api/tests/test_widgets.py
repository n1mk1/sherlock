"""Widgets (TRD §4.5, §6.3): SQL compile and validation, data with global filters and the cache,
CRUD with soft delete and undo, layout, selections."""

import json

import pytest

from sherlock.config import get_settings
from sherlock.db.connection import connect
from sherlock.steps.commit import Context, StepSpec, commit_step
from sherlock.widgets import compile as wc
from sherlock.widgets import layout as wl
from tests.test_rows import ds, typed_version  # noqa: F401  (fixture)
from tests.test_steps import sql_step

API = "/api/v1"
SPEC = {
    "scope": {"columns": {"x": "city", "y": "fare", "agg": "avg"}},
    "op": {"type": "sql", "sql": "SELECT city, AVG(fare) AS avg_fare, COUNT(*) AS n FROM t WHERE {{rows}} GROUP BY 1 ORDER BY 1"},
    "view": {"type": "bar", "options": {"x": "city", "y": "avg_fare"}},
}


# --- compile ----------------------------------------------------------------------------------


def test_validate_select_appends_limit_and_refuses_other_statements():
    assert wc.validate_select("SELECT a FROM t;").endswith("LIMIT 2000")
    assert wc.validate_select("SELECT a FROM t LIMIT 5") == "SELECT a FROM t LIMIT 5"
    assert wc.validate_select("WITH x AS (SELECT a FROM t) SELECT * FROM x").endswith("LIMIT 2000")
    for bad, message in [
        ("DROP TABLE t", "Only SELECT"),
        ("SELECT 1; SELECT 2", "exactly one"),
        ("SELECT * FROM read_csv('/etc/passwd')", "only read the table t"),
        ("SELECT * FROM 'x.parquet'", "only read the table t"),
        ("SELECT * FROM main.t", "only read the table t"),
        ("SELECT * FROM other", "only read the table t"),
        ("SELEC a FROM t", "doesn't parse"),
    ]:
        with pytest.raises(wc.SqlError, match=message):
            wc.validate_select(bad)


def test_compile_requires_rows_and_renders_literal_filters():
    with pytest.raises(wc.SqlError, match="WHERE {{rows}}"):
        wc.compile_sql("SELECT * FROM t", "1=1")
    types = {"pclass": "BIGINT", "sex": "VARCHAR", "fare": "DOUBLE", "alive": "BOOLEAN"}
    f = wc.filter_sql(wc.parse_filter({"and": [
        {"col": "pclass", "op": "eq", "value": "3"}, {"col": "sex", "op": "eq", "value": "O'Brien"},
        {"col": "fare", "op": "gt", "value": 7.5}, {"col": "alive", "op": "eq", "value": True},
        {"col": "pclass", "op": "in", "value": [1, 2]}]}), types)
    assert f == ('"pclass" = 3 AND "sex" = \'O\'\'Brien\' AND "fare" > 7.5 AND "alive" = TRUE AND "pclass" IN (1, 2)')
    rows = wc.rows_clause("age > 1", None, f)
    assert rows.startswith("_quarantine_reason IS NULL AND (age > 1) AND (")
    with pytest.raises(wc.SqlError, match="unknown column"):
        wc.filter_sql([{"col": "nope", "op": "eq", "value": 1}], types)


def test_predicate_validation():
    assert wc.validate_predicate("pclass = 3 AND sex = 'female'", ["pclass", "sex"]) == "pclass = 3 AND sex = 'female'"
    with pytest.raises(wc.SqlError, match="Unknown column"):
        wc.validate_predicate("nope = 1", ["pclass"])
    with pytest.raises(wc.SqlError, match="can't contain a query"):
        wc.validate_predicate("pclass IN (SELECT pclass FROM t)", ["pclass"])
    with pytest.raises(wc.SqlError):
        wc.validate_predicate("1=1; DROP TABLE t", ["pclass"])
    assert wc.validate_predicate("(pclass = 1) OR (pclass = 2)", ["pclass"]) == "(pclass = 1) OR (pclass = 2)"
    with pytest.raises(wc.SqlError, match="unbalanced parentheses"):
        wc.validate_predicate("pclass = 1) OR (1 = 1", ["pclass"])


def test_rows_must_be_anded_into_every_read_of_t():
    rows = wc.rows_clause(None, None, None)
    for ok in [
        "SELECT a FROM t WHERE {{rows}}",
        "SELECT a FROM t WHERE b = 1 AND ({{rows}} AND c = 2)",
        "WITH x AS (SELECT a FROM t WHERE {{rows}}) SELECT * FROM x",
        "SELECT a, count(*) * 1.0 / (SELECT count(*) FROM t WHERE {{rows}}) FROM t WHERE {{rows}} GROUP BY 1",
        "SELECT a FROM t WHERE {{rows}} UNION ALL SELECT b FROM t WHERE {{rows}}",
    ]:
        assert "_quarantine_reason IS NULL" in wc.compile_sql(ok, rows)
    for bad, message in [
        ("SELECT a FROM t WHERE {{rows}} OR 1=1", "ANDed into the WHERE"),
        ("SELECT a FROM t WHERE NOT ({{rows}})", "ANDed into the WHERE"),
        ("SELECT a FROM t WHERE b = 1 AND {{rows}} OR b = 2", "ANDed into the WHERE"),
        ("SELECT CASE WHEN {{rows}} THEN 1 END FROM t WHERE {{rows}}", "ANDed into the WHERE"),
        ("SELECT a FROM t GROUP BY a HAVING {{rows}}", "ANDed into the WHERE"),
        ("SELECT (SELECT count(*) FROM t) AS everyone FROM t WHERE {{rows}}", "Every SELECT that reads t"),
        ("SELECT a FROM t WHERE {{rows}} UNION ALL SELECT b FROM t", "Every SELECT that reads t"),
    ]:
        with pytest.raises(wc.SqlError, match=message):
            wc.compile_sql(bad, rows)


def test_pack_puts_kpis_first_then_packs_left_to_right():
    lay = wl.pack([("a", "bar"), ("k1", "kpi"), ("b", "line"), ("c", "table"), ("k2", "kpi")])["lg"]
    pos = {it["i"]: (it["x"], it["y"], it["w"], it["h"]) for it in lay}
    assert pos["k1"] == (0, 0, 3, 3) and pos["k2"] == (3, 0, 3, 3)
    assert pos["a"] == (0, 3, 6, 7) and pos["b"] == (6, 3, 6, 7) and pos["c"] == (0, 10, 6, 8)


# --- API --------------------------------------------------------------------------------------


@pytest.fixture
def typed(app, client, ds):  # noqa: F811
    typed_version(app, ds["id"])
    return ds


def create(client, ds_id, spec=SPEC, **extra):
    r = client.post(f"{API}/datasets/{ds_id}/widgets", json={**spec, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def test_create_list_data_and_filters(client, typed):
    out = create(client, typed["id"], title="Fare by city")
    w = out["widget"]
    assert w["title"] == "Fare by city" and w["status"] == "ready" and w["created_by"] == "user" and "warning" not in out
    assert w["version_built"] == 2 and w["spec"]["view"]["from"] == "result"

    listed = client.get(f"{API}/datasets/{typed['id']}/widgets").json()
    assert [x["id"] for x in listed["widgets"]] == [w["id"]]
    assert listed["layout"]["lg"] == [{"i": w["id"], "x": 0, "y": 0, "w": 6, "h": 7}]

    data = client.get(f"{API}/widgets/{w['id']}/data").json()
    assert data["version"] == 2 and data["truncated"] is False
    assert [c["name"] for c in data["columns"]] == ["city", "avg_fare", "n"]
    assert data["columns"][1]["type"] == "DOUBLE"
    assert data["rows"] == [["Lyon", 8.05, 1], ["Paris", 3.125, 2], [None, 100.0, 1]]

    f = json.dumps({"and": [{"col": "city", "op": "eq", "value": "Paris"}]})
    assert client.get(f"{API}/widgets/{w['id']}/data", params={"filters": f}).json()["rows"] == [["Paris", 3.125, 2]]
    explain = client.get(f"{API}/widgets/{w['id']}/explain", params={"filters": f}).json()
    assert explain["sql"] == (
        "SELECT city, AVG(fare) AS avg_fare, COUNT(*) AS n FROM t WHERE _quarantine_reason IS NULL AND (1=1) "
        "AND (\"city\" = 'Paris') GROUP BY 1 ORDER BY 1\nLIMIT 2000")
    # Version 1 is all text, so averaging fare there fails with the reason.
    r = client.get(f"{API}/widgets/{w['id']}/data", params={"version": 1})
    assert r.status_code == 422 and r.json()["error"]["message"].startswith("The query failed")


def test_widget_that_ignores_global_filters(client, typed):
    spec = json.loads(json.dumps(SPEC))
    spec["scope"]["rows"] = {"inherit_global_filters": False, "predicate": "fare > 5"}
    w = create(client, typed["id"])["widget"]
    w2 = create(client, typed["id"], spec)["widget"]
    f = json.dumps({"and": [{"col": "city", "op": "eq", "value": "Lyon"}]})
    assert len(client.get(f"{API}/widgets/{w['id']}/data", params={"filters": f}).json()["rows"]) == 1
    assert client.get(f"{API}/widgets/{w2['id']}/data", params={"filters": f}).json()["rows"] == [
        ["Lyon", 8.05, 1], ["Paris", 7.25, 1], [None, 100.0, 1]]


def test_quarantined_rows_are_excluded(app, client, typed):
    db = connect(get_settings())
    ctx = Context(get_settings(), db, app.state.duckdb)
    commit_step(ctx, typed["id"], 2, StepSpec(kind="clean", summary="Quarantine Dee", created_by="system",
                                              notebook_code="result = df\ndf = result\n", gate="commit"),
                sql_step("SELECT * REPLACE (CASE WHEN name = 'Dee' THEN 'test' END AS _quarantine_reason) FROM old"))
    db.close()
    w = create(client, typed["id"])["widget"]
    assert [r[0] for r in client.get(f"{API}/widgets/{w['id']}/data").json()["rows"]] == ["Lyon", "Paris"]


def test_bad_specs_are_refused(client, typed):
    base = typed["id"]
    for spec, message in [
        ({**SPEC, "op": {"type": "sql", "sql": "SELECT * FROM t"}}, "WHERE {{rows}}"),
        ({**SPEC, "op": {"type": "sql", "sql": "SELECT nope FROM t WHERE {{rows}}"}}, "The query failed"),
        ({**SPEC, "view": {"type": "sparkle"}}, "spec.view.type"),
        ({**SPEC, "op": {"type": "sql", "sql": "DELETE FROM t WHERE {{rows}}"}}, "Only SELECT"),
    ]:
        r = client.post(f"{API}/datasets/{base}/widgets", json=spec)
        assert r.status_code == 422, r.text
        assert message in r.json()["error"]["message"]
    assert client.get(f"{API}/datasets/{base}/widgets").json()["widgets"] == []


def test_patch_undo_duplicate_delete_restore(client, typed):
    w = create(client, typed["id"])["widget"]
    r = client.patch(f"{API}/widgets/{w['id']}", json={"view": {"type": "table"}, "title": "As a table"})
    assert r.status_code == 200, r.text
    assert r.json()["spec"]["view"]["type"] == "table" and r.json()["title"] == "As a table"
    assert r.json()["spec"]["op"]["sql"] == SPEC["op"]["sql"]  # merged, not replaced
    assert client.post(f"{API}/widgets/{w['id']}/undo").json()["spec"]["view"]["type"] == "bar"
    assert client.post(f"{API}/widgets/{w['id']}/undo").json()["spec"]["view"]["type"] == "table"

    copy = client.post(f"{API}/widgets/{w['id']}/duplicate").json()
    assert copy["title"] == "As a table (copy)" and copy["id"] != w["id"]

    assert client.delete(f"{API}/widgets/{w['id']}").status_code == 204
    assert [x["id"] for x in client.get(f"{API}/datasets/{typed['id']}/widgets").json()["widgets"]] == [copy["id"]]
    assert client.get(f"{API}/widgets/{w['id']}/data").status_code == 404
    restored = client.post(f"{API}/widgets/{w['id']}/restore").json()
    assert restored["deleted_at"] is None
    assert len(client.get(f"{API}/datasets/{typed['id']}/widgets").json()["widgets"]) == 2


def test_layout_round_trip_and_unknown_ids(client, typed):
    a = create(client, typed["id"])["widget"]
    b = create(client, typed["id"])["widget"]
    layout = {"lg": [{"i": a["id"], "x": 6, "y": 0, "w": 6, "h": 7}, {"i": b["id"], "x": 0, "y": 0, "w": 6, "h": 7, "collapsed": True}]}
    r = client.put(f"{API}/datasets/{typed['id']}/layout", json=layout)
    assert r.status_code == 200, r.text
    got = client.get(f"{API}/datasets/{typed['id']}/widgets").json()["layout"]
    assert got["lg"][1]["collapsed"] is True and got["lg"][0]["x"] == 6
    # A new widget goes under the saved layout.
    c = create(client, typed["id"])["widget"]
    got = client.get(f"{API}/datasets/{typed['id']}/widgets").json()["layout"]["lg"]
    assert got[-1] == {"i": c["id"], "x": 0, "y": 7, "w": 6, "h": 7}
    bad = client.put(f"{API}/datasets/{typed['id']}/layout", json={"lg": [{"i": "wdg_nope", "x": 0, "y": 0, "w": 3, "h": 3}]})
    assert bad.status_code == 422


def test_soft_cap_warning(client, typed):
    db = connect(get_settings())
    db.executemany(
        "INSERT INTO widgets (id, dataset_id, title, spec_json, spec_hash, status, version_built, created_by, order_no, "
        "created_at, updated_at) VALUES (?, ?, 't', ?, 'h', 'ready', 2, 'user', ?, 'now', 'now')",
        [(f"wdg_{i}", typed["id"], json.dumps(SPEC), i) for i in range(20)],
    )
    db.close()
    assert create(client, typed["id"])["warning"].startswith("This dashboard has 20 or more widgets")


def test_selections(client, typed):
    r = client.post(f"{API}/datasets/{typed['id']}/selections", json={"predicate": "fare > 7.5"})
    assert r.status_code == 201, r.text
    sel = r.json()
    assert sel["row_count"] == 2
    rows = client.get(f"{API}/datasets/{typed['id']}/rows", params={"selection": sel["selection_id"]}).json()
    assert [x["_row_id"] for x in rows["rows"]] == [2, 4]
    r = client.post(f"{API}/datasets/{typed['id']}/selections", json={"row_ids": [1, 3, 99]})
    assert r.json()["row_count"] == 2
    spec = json.loads(json.dumps(SPEC))
    spec["scope"]["rows"] = {"selection_id": r.json()["selection_id"]}
    w = create(client, typed["id"], spec)["widget"]
    assert [row[0] for row in client.get(f"{API}/widgets/{w['id']}/data").json()["rows"]] == ["Paris"]
    for body in ({"predicate": "nope > 1"}, {}, {"predicate": "a", "row_ids": [1]}, {"row_ids": ["x"]}):
        assert client.post(f"{API}/datasets/{typed['id']}/selections", json=body).status_code == 422


def test_other_users_cannot_reach_widgets(app, client, typed):
    from fastapi.testclient import TestClient

    w = create(client, typed["id"])["widget"]
    with TestClient(app) as other:
        assert other.get(f"{API}/widgets/{w['id']}/data").status_code == 404
        assert other.delete(f"{API}/widgets/{w['id']}").status_code == 404
        assert other.get(f"{API}/datasets/{typed['id']}/widgets").status_code == 404
