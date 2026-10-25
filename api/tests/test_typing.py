import duckdb
import pandas as pd
import pytest

from sherlock.profile import typing as typing_step
from tests.test_jobs import upload, wait_status

API = "/api/v1"
pytestmark = pytest.mark.usefixtures("run_jobs")


def frame_conn(columns: dict[str, list]) -> duckdb.DuckDBPyConnection:
    n = len(next(iter(columns.values())))
    df = pd.DataFrame({"_row_id": range(1, n + 1), "_quarantine_reason": [None] * n, **columns})
    df = df.astype({c: object for c in columns})
    conn = duckdb.connect()
    conn.register("src", df)
    conn.execute("CREATE TABLE t AS SELECT _row_id::BIGINT AS _row_id, _quarantine_reason::VARCHAR AS _quarantine_reason, "
                 + ", ".join(f'"{c}"::VARCHAR AS "{c}"' for c in columns) + " FROM src")
    return conn


def test_plan_casts_only_lossless_columns():
    n = 200
    conn = frame_conn({
        "qty": [str(i) for i in range(n - 2)] + ["N/A", None],
        "code": [f"{i:03d}" for i in range(n)],          # leading zeros: stays text
        "price": [f"{i}.5" for i in range(n - 1)] + ["oops"],
        "flag": ["yes", "no"] * (n // 2),
        "day": [f"2024-01-{(i % 28) + 1:02d}" for i in range(n)],
        "city": ["Paris", "Lyon"] * (n // 2),
    })
    casts = typing_step.plan(conn)
    assert set(casts) == {"qty", "price", "flag", "day"}

    sql = typing_step.statement(["qty", "code", "price", "flag", "day", "city"], casts)
    conn.execute("CREATE VIEW df AS SELECT * FROM t")
    types = {r[0]: r[1] for r in conn.execute(f"DESCRIBE ({sql})").fetchall()}
    assert (types["qty"], types["code"], types["price"], types["flag"], types["day"]) == (
        "BIGINT", "VARCHAR", "DOUBLE", "BOOLEAN", "DATE")
    out = conn.execute(f"SELECT * FROM ({sql})").df()
    assert out["qty"].isna().sum() == 2                      # the sentinel became NULL; no quarantine
    bad = out[out["_quarantine_reason"].notna()]
    assert bad["_quarantine_reason"].tolist() == ["type: price"] and bad["_row_id"].tolist() == [n]

    # The same statement runs over a pandas DataFrame named df (the exported notebook).
    df = conn.execute("SELECT * FROM t").df()
    result = duckdb.sql(sql).df()
    assert result["price"].dtype == "float64" and len(result) == len(df) == n


def test_casts_that_would_lose_information_are_refused():
    # Review Day 2 M2: 20-digit floats were rounded, and offsets and nanoseconds were dropped, with no quarantine.
    n = 200
    conn = frame_conn({
        "x": [f"{i}.25" for i in range(n - 1)] + ["0.12345678901234567890"],
        "big": ["1e300", "123456789012345", "-0.000001500"] * (n // 4) + ["1.0"] * (n - 3 * (n // 4)),
        "ns": [f"2024-01-15 10:{i % 60:02d}:00" for i in range(n - 2)] + ["2024-01-15 10:00:00.123456789", None],
        "india": [f"2024-01-15 10:{i % 60:02d}:00+05:30" for i in range(n)],  # TIMESTAMP would drop the offset
        "utc": [f"2024-01-15T10:{i % 60:02d}:00Z" for i in range(n)],          # Z is UTC: nothing is lost
    })
    casts = typing_step.plan(conn)
    assert set(casts) == {"x", "big", "ns", "utc"}
    sql = typing_step.statement(["x", "big", "ns", "india", "utc"], casts)
    conn.execute("CREATE VIEW df AS SELECT * FROM t")
    out = conn.execute(f"SELECT * FROM ({sql}) ORDER BY _row_id").df()
    assert out.loc[n - 1, "_quarantine_reason"] == "type: x" and pd.isna(out.loc[n - 1, "x"])
    assert out["big"].notna().all()  # 15 significant digits or fewer cast exactly
    assert out.loc[n - 2, "_quarantine_reason"] == "type: ns" and pd.isna(out.loc[n - 2, "ns"])  # nanoseconds
    assert out.loc[0, "utc"] == pd.Timestamp("2024-01-15 10:00:00") and out["india"].dtype == object
    assert typing_step.verify(conn, f"({sql})", casts) == {"row_ledger": "pass", "lossless": "pass"}
    # The checks catch a value lost without its row quarantined, and a dropped row.
    unquarantined = f"(SELECT * REPLACE (NULL::VARCHAR AS _quarantine_reason) FROM ({sql}))"
    assert typing_step.verify(conn, unquarantined, casts)["lossless"] == "fail"
    assert typing_step.verify(conn, f"(SELECT * FROM ({sql}) WHERE _row_id > 1)", casts)["row_ledger"] == "fail"


def test_upload_commits_the_typing_step_as_step_one(client):
    csv = "id,age,score,joined\n" + "".join(f"{i},{20 + i % 50},{i}.25,2024-02-{(i % 28) + 1:02d}\n" for i in range(150))
    csv += "150,abc,1.0,2024-01-01\n"  # one age that isn't a number: quarantined
    ds = upload(client, csv.encode())
    done = wait_status(client, ds["id"], "offer", "failed")
    assert done["status"] == "offer" and done["current_version"] == 2

    [step] = client.get(f"{API}/datasets/{ds['id']}/steps").json()
    assert (step["no"], step["kind"], step["created_by"], step["gate"]) == (1, "clean", "system", "commit")
    assert step["summary"].startswith("Typed 4 columns from text: id, age, score, joined")
    assert step["notebook_code"].startswith('result = duckdb.sql("""') and step["notebook_code"].endswith("df = result\n")
    assert step["impact"]["quarantined"] == 1

    card = client.get(f"{API}/datasets/{ds['id']}/datacard").json()
    assert card["version"] == 2 and card["quarantined"] == 1
    assert {c["name"]: c["type"] for c in card["columns"]}["age"] == "int"

    page = client.get(f"{API}/datasets/{ds['id']}/rows", params={"view": "flagged"}).json()
    [row] = page["rows"]
    assert row["quarantined"] and row["quarantine_reason"] == "type: age" and row["marks"] == {"age": "invalid"}
    history = client.get(f"{API}/datasets/{ds['id']}/cells/{row['_row_id']}/age/history").json()["entries"]
    assert history[0]["old"] == "abc" and history[0]["new"] is None and history[0]["flag"] == "quarantined"

    # Undoing it warns first, even though it's the latest step.
    r = client.post(f"{API}/datasets/{ds['id']}/steps/{step['id']}/undo", json={"base_version": 2}).json()
    assert r == {"confirm_required": True, "replay_needed": [], "warning": "typing"}


def test_mixed_utc_offsets_stay_text_and_profile(client):
    """Daylight saving gives one column two offsets; pandas can't hold that as datetimes."""
    lines = ["ts,v"] + [f"2024-{(i % 12) + 1:02d}-15 10:00:00-0{4 + i % 2}:00,{i}" for i in range(40)]
    ds = upload(client, ("\n".join(lines) + "\n").encode())
    done = wait_status(client, ds["id"], "offer", "failed")
    assert done["status"] == "offer", done.get("error")
    card = client.get(f"{API}/datasets/{ds['id']}/datacard").json()
    assert {c["name"]: c["type"] for c in card["columns"]}["ts"] not in ("date", "datetime")


def test_all_text_file_gets_no_typing_step(client):
    ds = upload(client, b"name,city\nAnn,Paris\nBob,Lyon\n")
    done = wait_status(client, ds["id"], "offer", "failed")
    assert done["current_version"] == 1
    assert client.get(f"{API}/datasets/{ds['id']}/steps").json() == []


def test_dataset_reports_issue_and_step_counts(client):
    ds = upload(client, b"name,age\n" + b"".join(f"P{i},{20 + i % 30}\n".encode() for i in range(40)) + b"Q,\n")
    assert ds["issue_count"] is None and ds["step_count"] == 0  # nothing profiled yet
    done = wait_status(client, ds["id"], "offer")
    assert done["step_count"] == 1 and done["issue_count"] >= 1  # the typing step; the missing age
    assert client.get(f"{API}/datasets").json()[0]["issue_count"] == done["issue_count"]
