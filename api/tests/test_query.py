"""Querying a version (TRD §6.3, §9): SQL compile and validation, the result cap, and selections."""

import pytest

from sherlock.query import compile as qc
from tests.test_rows import ds, typed_version  # noqa: F401  (fixture)

API = "/api/v1"


# --- compile ----------------------------------------------------------------------------------


def test_validate_select_appends_limit_and_refuses_other_statements():
    assert qc.validate_select("SELECT a FROM t;").endswith("LIMIT 2000")
    assert qc.validate_select("SELECT a FROM t LIMIT 5") == "SELECT a FROM t LIMIT 5"
    assert qc.validate_select("WITH x AS (SELECT a FROM t) SELECT * FROM x").endswith("LIMIT 2000")
    for bad, message in [
        ("DROP TABLE t", "Only SELECT"),
        ("SELECT 1; SELECT 2", "exactly one"),
        ("SELECT * FROM read_csv('/etc/passwd')", "only read the table t"),
        ("SELECT * FROM 'x.parquet'", "only read the table t"),
        ("SELECT * FROM main.t", "only read the table t"),
        ("SELECT * FROM other", "only read the table t"),
        ("SELEC a FROM t", "doesn't parse"),
    ]:
        with pytest.raises(qc.SqlError, match=message):
            qc.validate_select(bad)


def test_compile_requires_rows_and_renders_literal_filters():
    with pytest.raises(qc.SqlError, match="WHERE {{rows}}"):
        qc.compile_sql("SELECT * FROM t", "1=1")
    types = {"pclass": "BIGINT", "sex": "VARCHAR", "fare": "DOUBLE", "alive": "BOOLEAN"}
    f = qc.filter_sql(qc.parse_filter({"and": [
        {"col": "pclass", "op": "eq", "value": "3"}, {"col": "sex", "op": "eq", "value": "O'Brien"},
        {"col": "fare", "op": "gt", "value": 7.5}, {"col": "alive", "op": "eq", "value": True},
        {"col": "pclass", "op": "in", "value": [1, 2]}]}), types)
    assert f == ('"pclass" = 3 AND "sex" = \'O\'\'Brien\' AND "fare" > 7.5 AND "alive" = TRUE AND "pclass" IN (1, 2)')
    rows = qc.rows_clause("age > 1", None, f)
    assert rows.startswith("_quarantine_reason IS NULL AND (age > 1) AND (")
    with pytest.raises(qc.SqlError, match="unknown column"):
        qc.filter_sql([{"col": "nope", "op": "eq", "value": 1}], types)


def test_contains_filter_is_a_plain_substring():
    # Review F15: `contains "%"` matched every row because `%` and `_` were wildcards.
    import duckdb
    conn = duckdb.connect()
    conn.execute("CREATE TABLE t AS SELECT * FROM (VALUES ('50% off'), ('half'), ('a_b'), ('ab'), ('c\\d')) v(s)")
    def hits(value):
        where = qc.filter_sql([{"col": "s", "op": "contains", "value": value}], {"s": "VARCHAR"})
        return [r[0] for r in conn.execute(f"SELECT s FROM t WHERE {where} ORDER BY s").fetchall()]
    assert hits("%") == ["50% off"]
    assert hits("_") == ["a_b"]
    assert hits("\\") == ["c\\d"]
    assert hits("HAL") == ["half"]


def test_predicate_validation():
    assert qc.validate_predicate("pclass = 3 AND sex = 'female'", ["pclass", "sex"]) == "pclass = 3 AND sex = 'female'"
    with pytest.raises(qc.SqlError, match="Unknown column"):
        qc.validate_predicate("nope = 1", ["pclass"])
    with pytest.raises(qc.SqlError, match="can't contain a query"):
        qc.validate_predicate("pclass IN (SELECT pclass FROM t)", ["pclass"])
    with pytest.raises(qc.SqlError):
        qc.validate_predicate("1=1; DROP TABLE t", ["pclass"])
    assert qc.validate_predicate("(pclass = 1) OR (pclass = 2)", ["pclass"]) == "(pclass = 1) OR (pclass = 2)"
    with pytest.raises(qc.SqlError, match="unbalanced parentheses"):
        qc.validate_predicate("pclass = 1) OR (1 = 1", ["pclass"])


def test_rows_must_be_anded_into_every_read_of_t():
    rows = qc.rows_clause(None, None, None)
    for ok in [
        "SELECT a FROM t WHERE {{rows}}",
        "SELECT a FROM t WHERE b = 1 AND ({{rows}} AND c = 2)",
        "WITH x AS (SELECT a FROM t WHERE {{rows}}) SELECT * FROM x",
        "SELECT a, count(*) * 1.0 / (SELECT count(*) FROM t WHERE {{rows}}) FROM t WHERE {{rows}} GROUP BY 1",
        "SELECT a FROM t WHERE {{rows}} UNION ALL SELECT b FROM t WHERE {{rows}}",
    ]:
        assert "_quarantine_reason IS NULL" in qc.compile_sql(ok, rows)
    for bad, message in [
        ("SELECT a FROM t WHERE {{rows}} OR 1=1", "ANDed into the WHERE"),
        ("SELECT a FROM t WHERE NOT ({{rows}})", "ANDed into the WHERE"),
        ("SELECT a FROM t WHERE b = 1 AND {{rows}} OR b = 2", "ANDed into the WHERE"),
        ("SELECT CASE WHEN {{rows}} THEN 1 END FROM t WHERE {{rows}}", "ANDed into the WHERE"),
        ("SELECT a FROM t GROUP BY a HAVING {{rows}}", "ANDed into the WHERE"),
        ("SELECT (SELECT count(*) FROM t) AS everyone FROM t WHERE {{rows}}", "Every SELECT that reads t"),
        ("SELECT a FROM t WHERE {{rows}} UNION ALL SELECT b FROM t", "Every SELECT that reads t"),
    ]:
        with pytest.raises(qc.SqlError, match=message):
            qc.compile_sql(bad, rows)


@pytest.fixture
def typed(app, client, ds):  # noqa: F811
    typed_version(app, ds["id"])
    return ds


def test_selections(client, typed):
    r = client.post(f"{API}/datasets/{typed['id']}/selections", json={"predicate": "fare > 7.5"})
    assert r.status_code == 201, r.text
    sel = r.json()
    assert sel["row_count"] == 2
    rows = client.get(f"{API}/datasets/{typed['id']}/rows", params={"selection": sel["selection_id"]}).json()
    assert [x["_row_id"] for x in rows["rows"]] == [2, 4]
    r = client.post(f"{API}/datasets/{typed['id']}/selections", json={"row_ids": [1, 3, 99]})
    assert r.json()["row_count"] == 2
    for body in ({"predicate": "nope > 1"}, {}, {"predicate": "a", "row_ids": [1]}, {"row_ids": ["x"]}):
        assert client.post(f"{API}/datasets/{typed['id']}/selections", json=body).status_code == 422


def test_a_capped_result_reports_its_real_row_count():
    """Plan 2b.6 (A33): `row_count` counts the rows returned, capped at `MAX_RESULT_ROWS`; `total` is the
    query's real count, which the notebook's "first 50 of N rows" now shows."""
    import duckdb

    from sherlock.notebook import outputs
    from sherlock.query.execute import run_query

    conn = duckdb.connect()
    conn.execute(f"CREATE TABLE t AS SELECT range AS v FROM range({qc.MAX_RESULT_ROWS + 500})")
    out = run_query(conn, "SELECT v FROM t")
    assert out["truncated"] and out["row_count"] == qc.MAX_RESULT_ROWS and out["total"] == qc.MAX_RESULT_ROWS + 500
    small = run_query(conn, "SELECT v FROM t LIMIT 3")
    assert not small["truncated"] and small["row_count"] == small["total"] == 3
    note = outputs.table(out["columns"], out["rows"], out["total"])["data"]["text/plain"]
    assert f"first 50 of {qc.MAX_RESULT_ROWS + 500:,} rows" in note
