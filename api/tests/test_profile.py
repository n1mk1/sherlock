import csv
import io
import time

from fastapi.testclient import TestClient

from sherlock.config import get_settings
from sherlock.db.connection import connect

API = "/api/v1"


def query(sql, *params):
    conn = connect(get_settings())
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


def test_sample_datacard(client):
    ds = client.post(f"{API}/datasets/sample").json()
    started = time.perf_counter()
    res = client.get(f"{API}/datasets/{ds['id']}/datacard")
    elapsed = time.perf_counter() - started
    assert res.status_code == 200, res.text
    card = res.json()
    assert elapsed < 3.0  # PRD PROF-1: 1,309 × 14 within 3 s

    assert (card["version"], card["row_count"], card["column_count"], card["quarantined"]) == (1, 1309, 14, 0)
    cols = {c["name"]: c for c in card["columns"]}
    assert set(cols["age"]) >= {"name", "type", "role", "missing", "missing_pct", "distinct", "stats",
                                "top_values", "sample_values", "flags", "unit", "semantic", "histogram"}
    assert (cols["age"]["type"], cols["age"]["role"], cols["age"]["missing"]) == ("float", "measure", 263)
    assert cols["age"]["missing_pct"] == 20.09
    assert len(cols["age"]["histogram"]["counts"]) == 20 and sum(cols["age"]["histogram"]["counts"]) == 1046
    assert cols["cabin"]["missing"] == 1014
    assert cols["survived"]["role"] == "target_like"
    assert cols["sex"]["top_values"] == [{"value": "male", "count": 843}, {"value": "female", "count": 466}]
    assert card["target_candidates"] == ["survived"]
    assert card["id_columns"] == ["name"]
    assert {c["column"] for c in card["leakage_candidates"]} == {"boat", "body"}

    severities = [i["severity"] for i in card["issues"]]
    assert severities == sorted(severities, reverse=True)
    assert {i["detector"] for i in card["issues"]} >= {"missing", "leakage", "id_candidates"}


def test_datacard_is_cached_with_issues_and_value_index(client):
    ds = client.post(f"{API}/datasets/sample").json()
    first = client.get(f"{API}/datasets/{ds['id']}/datacard").json()
    second = client.get(f"{API}/datasets/{ds['id']}/datacard?version=1").json()
    assert first == second  # same stored card, same issue ids

    assert query("SELECT count(*) FROM datacards WHERE dataset_id = ?", ds["id"])[0][0] == 1
    issues = query("SELECT detector, column, count FROM issues WHERE dataset_id = ? AND version = 1", ds["id"])
    assert len(issues) == len(first["issues"])
    assert ("missing", "age", 263) in [tuple(r) for r in issues]

    index = dict(query("SELECT value, count FROM value_index WHERE dataset_id = ? AND column = 'sex'", ds["id"]))
    assert index == {"male": 843, "female": 466}
    indexed_columns = {r[0] for r in query("SELECT DISTINCT column FROM value_index WHERE dataset_id = ?", ds["id"])}
    assert "age" not in indexed_columns and "name" not in indexed_columns  # measures and ids aren't indexed


def test_unknown_version_and_other_users(app):
    with TestClient(app) as alice, TestClient(app) as bob:
        ds = alice.post(f"{API}/datasets/sample").json()
        missing = alice.get(f"{API}/datasets/{ds['id']}/datacard?version=2")
        assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
        assert alice.get(f"{API}/datasets/{ds['id']}/datacard?version=0").status_code == 422
        assert bob.get(f"{API}/datasets/{ds['id']}/datacard").status_code == 404


def test_uploaded_messy_file(client):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["id", "price", "city", "joined"])
    for i in range(60):
        price = ["$1,200", "45", "N/A", "€3,50"][i % 4]
        city = ["Paris", "paris", "London", "Lodnon"][i % 4] if i % 10 else "London"
        writer.writerow([i, price, city, f"2026-0{1 + i % 9}-1{i % 10}"])
    content = out.getvalue().encode()
    ds = client.post(f"{API}/datasets", files={"file": ("messy.csv", content)}).json()
    card = client.get(f"{API}/datasets/{ds['id']}/datacard").json()
    found = {(i["detector"], i["column"]) for i in card["issues"]}
    assert ("numbers_as_text", "price") in found
    assert ("sentinels", "price") in found
    assert ("whitespace_case", "city") in found
    assert {c["name"]: c["type"] for c in card["columns"]}["joined"] == "date"
