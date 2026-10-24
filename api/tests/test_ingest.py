import json
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from sherlock.config import get_settings
from sherlock.db.connection import connect
from sherlock.ingest.importer import column_names
from sherlock.routers.datasets import SAMPLE_CSV
from sherlock.storage import VersionConnections, dataset_dir, version_path

API = "/api/v1"


def upload(client, content: bytes, filename="data.csv", options=None):
    data = {"options": json.dumps(options)} if options is not None else {}
    return client.post(f"{API}/datasets", files={"file": (filename, content, "text/csv")}, data=data)


def db_row(sql, *params):
    conn = connect(get_settings())
    try:
        return conn.execute(sql, params).fetchone()
    finally:
        conn.close()


def folder_of(client, dataset_id) -> Path:
    user_id = client.get(f"{API}/me").json()["user_id"]
    return dataset_dir(get_settings(), user_id, dataset_id)


def read_version(app, dataset_id, folder, sql):
    with app.state.duckdb.connection(dataset_id, 1, version_path(folder, 1)) as conn:
        return conn.execute(sql).fetchall()


# --- sample ---------------------------------------------------------------------------


def test_sample_creates_titanic_once(client):
    first = client.post(f"{API}/datasets/sample")
    assert first.status_code == 201
    body = first.json()
    assert body["name"] == "titanic3.csv (sample)"
    assert (body["row_count"], body["column_count"]) == (1309, 14)
    assert body["status"] == "profiling"
    assert body["current_version"] == 1

    again = client.post(f"{API}/datasets/sample")
    assert again.status_code == 200
    assert again.json()["id"] == body["id"]
    assert [d["id"] for d in client.get(f"{API}/datasets").json()] == [body["id"]]


def test_sample_version_is_readable_through_duckdb(app, client):
    ds = client.post(f"{API}/datasets/sample").json()
    folder = folder_of(client, ds["id"])

    assert (folder / "raw.csv").read_bytes() == SAMPLE_CSV.read_bytes()  # raw kept unmodified
    assert not list(folder.glob(".ingest*"))  # temporary UTF-8 copy removed

    (count, min_id, max_id, distinct), = read_version(
        app, ds["id"], folder, "SELECT count(*), min(_row_id), max(_row_id), count(DISTINCT _row_id) FROM t")
    assert (count, min_id, max_id, distinct) == (1309, 1, 1309, 1309)
    (missing_age, quarantined), = read_version(
        app, ds["id"], folder, "SELECT count(*) - count(age), count(_quarantine_reason) FROM t")
    assert (missing_age, quarantined) == (263, 0)
    (name,), = read_version(app, ds["id"], folder, "SELECT name FROM t WHERE _row_id = 1")
    assert name == "Allen, Miss. Elisabeth Walton"
    types = read_version(app, ds["id"], folder, "SELECT column_type FROM (DESCRIBE t)")
    assert {t for (t,) in types[2:]} == {"VARCHAR"}  # all_varchar until the typing step

    version = db_row("SELECT * FROM versions WHERE dataset_id = ?", ds["id"])
    assert version["parquet_path"] == "versions/v1.parquet"
    assert [c["name"] for c in json.loads(version["columns_json"])][:3] == ["_row_id", "_quarantine_reason", "pclass"]
    dataset = db_row("SELECT * FROM datasets WHERE id = ?", ds["id"])
    assert dataset["next_row_id"] == 1310
    assert json.loads(dataset["import_options_json"]) == {
        "delimiter": ",", "encoding": "utf-8", "header_row": 1, "skip_rows": 0,
    }
    user = db_row("SELECT storage_bytes FROM users WHERE id = ?", dataset["user_id"])
    assert user["storage_bytes"] == dataset["folder_bytes"] > 0


def test_cached_connection_cannot_read_files(app, client):
    ds = client.post(f"{API}/datasets/sample").json()
    folder = folder_of(client, ds["id"])
    with app.state.duckdb.connection(ds["id"], 1, version_path(folder, 1)) as conn:
        with pytest.raises(duckdb.Error):
            conn.execute(f"SELECT * FROM read_csv('{SAMPLE_CSV.as_posix()}')").fetchall()


# --- uploads --------------------------------------------------------------------------


def test_semicolon_latin1_file(app, client):
    content = "id;name;city\n1;Zoë;Malmö\n2;José;São Paulo\n".encode("latin-1")
    res = upload(client, content, "people.csv")
    assert res.status_code == 201, res.text
    ds = res.json()
    folder = folder_of(client, ds["id"])
    rows = read_version(app, ds["id"], folder, "SELECT name, city FROM t ORDER BY _row_id")
    assert rows == [("Zoë", "Malmö"), ("José", "São Paulo")]
    options = json.loads(db_row("SELECT import_options_json FROM datasets WHERE id = ?", ds["id"])[0])
    assert options["delimiter"] == ";"
    assert options["encoding"] != "utf-8"


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16"])
def test_bom_encodings(app, client, encoding):
    res = upload(client, "a,b\nx,ñ\n".encode(encoding))
    assert res.status_code == 201, res.text
    ds = res.json()
    rows = read_version(app, ds["id"], folder_of(client, ds["id"]), "SELECT a, b FROM t")
    assert rows == [("x", "ñ")]


def test_header_after_preamble_with_explicit_options(app, client):
    content = b"Exported by Some Tool\nGenerated 2026-10-24\nid|value\n1|10\n2|20\n"
    res = upload(client, content, "broken.txt", {"delimiter": "|", "skip_rows": 2, "header_row": 1})
    assert res.status_code == 201, res.text
    ds = res.json()
    assert ds["row_count"] == 2
    rows = read_version(app, ds["id"], folder_of(client, ds["id"]), "SELECT id, value FROM t ORDER BY _row_id")
    assert rows == [("1", "10"), ("2", "20")]


def test_preamble_semicolon_latin1_is_auto_detected(app, client):
    # Like samples' broken_latin1.txt (Implementation Plan §6): Latin-1, ';', header on line 3.
    content = (
        "Quarterly export\nGenerated by ERP 2026\nregion;product;amount;note\n"
        "Nord;Käse;12,50;größer\nSüd;Brot;3,10;\nWest;Äpfel;7,00;frisch\n"
    ).encode("latin-1")
    res = upload(client, content, "broken_latin1.txt")
    assert res.status_code == 201, res.text
    ds = res.json()
    assert (ds["row_count"], ds["column_count"]) == (3, 4)
    options = json.loads(db_row("SELECT import_options_json FROM datasets WHERE id = ?", ds["id"])[0])
    assert options == {"delimiter": ";", "encoding": "cp1252", "header_row": 1, "skip_rows": 2}
    rows = read_version(app, ds["id"], folder_of(client, ds["id"]), "SELECT region, product, note FROM t ORDER BY _row_id")
    assert rows[:2] == [("Nord", "Käse", "größer"), ("Süd", "Brot", None)]


def test_cjk_double_byte_is_still_detected(app, client):
    content = "名前,都市,金額\n山田太郎,東京都,1200\n佐藤花子,大阪府,980\n鈴木一郎,名古屋市,450\n".encode("shift_jis")
    res = upload(client, content, "jp.csv")
    assert res.status_code == 201, res.text
    ds = res.json()
    rows = read_version(app, ds["id"], folder_of(client, ds["id"]), 'SELECT "名前", "都市" FROM t ORDER BY _row_id')
    assert rows[0] == ("山田太郎", "東京都")


def test_no_header_option_names_columns(app, client):
    res = upload(client, b"1,2,3\n4,5,6\n", options={"header_row": 0})
    assert res.status_code == 201, res.text
    ds = res.json()
    assert ds["row_count"] == 2
    cols = read_version(app, ds["id"], folder_of(client, ds["id"]), "SELECT column_name FROM (DESCRIBE t)")
    assert [c for (c,) in cols] == ["_row_id", "_quarantine_reason", "col_1", "col_2", "col_3"]


def test_duplicate_blank_and_reserved_headers(app, client):
    res = upload(client, b"a,a,,_row_id\n1,2,3,4\n")
    assert res.status_code == 201, res.text
    ds = res.json()
    cols = read_version(app, ds["id"], folder_of(client, ds["id"]), "SELECT column_name FROM (DESCRIBE t)")
    assert [c for (c,) in cols][2:] == ["a", "a_2", "col_3", "_row_id_2"]


def test_column_names_rules():
    assert column_names(["x", " x ", "", "_quarantine_reason"], 5) == [
        "x", "x_2", "col_3", "_quarantine_reason_2", "col_5",
    ]


# --- refusals: nothing is created ----------------------------------------------------


def assert_nothing_created(client):
    assert client.get(f"{API}/datasets").json() == []
    user_id = client.get(f"{API}/me").json()["user_id"]
    root = get_settings().data_dir / "users" / user_id / "datasets"
    assert not root.exists() or not any(root.iterdir())


@pytest.mark.parametrize("content", [b"", b"a,b,c\n", b"\n\n"])
def test_no_data_rows(client, content):
    res = upload(client, content)
    assert res.status_code == 422
    assert res.json()["error"] == {
        "code": "invalid", "message": "This file has no data rows.",
        "request_id": res.headers["x-request-id"],
    }
    assert_nothing_created(client)


def test_binary_file_is_refused(client):
    res = upload(client, b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(200), "chart.png")
    assert res.status_code == 422
    assert res.json()["error"]["message"].startswith("Couldn't read this as text.")
    assert_nothing_created(client)


def test_limits(monkeypatch, app):
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    monkeypatch.setenv("MAX_ROWS", "3")
    monkeypatch.setenv("MAX_COLUMNS", "2")
    get_settings.cache_clear()
    from sherlock.main import create_app

    with TestClient(create_app()) as client:
        big = upload(client, b"a\n" + b"x\n" * 600_000)
        assert big.status_code == 413
        assert big.json()["error"]["message"] == "This file is 1.1 MB. The limit is 1 MB."
        rows = upload(client, b"a\n1\n2\n3\n4\n")
        assert rows.status_code == 413 and "rows" in rows.json()["error"]["message"]
        cols = upload(client, b"a,b,c\n1,2,3\n")
        assert cols.status_code == 413 and "columns" in cols.json()["error"]["message"]
        assert_nothing_created(client)


def test_user_storage_limit(monkeypatch):
    monkeypatch.setenv("USER_STORAGE_MB", "0")
    get_settings.cache_clear()
    from sherlock.main import create_app

    with TestClient(create_app()) as client:
        res = client.post(f"{API}/datasets/sample")
        assert res.status_code == 413
        assert "delete a CSV" in res.json()["error"]["message"]
        assert_nothing_created(client)


def test_bad_options(client):
    assert upload(client, b"a\n1\n", options={"delimiter": ";;"}).status_code == 422
    res = client.post(f"{API}/datasets", files={"file": ("x.csv", b"a\n1\n")}, data={"options": "{nope"})
    assert res.status_code == 422 and res.json()["error"]["code"] == "invalid"
    assert upload(client, b"a\n1\n", options={"encoding": "klingon"}).status_code == 422


# --- listing and ownership ------------------------------------------------------------


def test_get_marks_opened_and_orders_library(client):
    a = upload(client, b"x\n1\n", "a.csv").json()
    b = upload(client, b"x\n1\n", "b.csv").json()
    assert [d["name"] for d in client.get(f"{API}/datasets").json()] == ["b.csv", "a.csv"]
    opened = client.get(f"{API}/datasets/{a['id']}").json()
    assert opened["last_opened_at"] is not None
    assert [d["id"] for d in client.get(f"{API}/datasets").json()] == [a["id"], b["id"]]


def test_other_users_cannot_see_datasets(app):
    with TestClient(app) as alice, TestClient(app) as bob:
        ds = alice.post(f"{API}/datasets/sample").json()
        assert bob.get(f"{API}/datasets").json() == []
        res = bob.get(f"{API}/datasets/{ds['id']}")
        assert res.status_code == 404 and res.json()["error"]["code"] == "not_found"
        # Bob's own sample is a separate dataset.
        assert bob.post(f"{API}/datasets/sample").json()["id"] != ds["id"]


# --- the version connection cache ----------------------------------------------------


def test_version_cache_evicts_old_versions_and_lru(tmp_path):
    settings = get_settings()
    cache = VersionConnections(settings, max_size=2)
    parquet = tmp_path / "v.parquet"
    duckdb.connect().execute(f"COPY (SELECT 1 AS x) TO '{parquet.as_posix()}' (FORMAT PARQUET)")
    with cache.connection("ds_a", 1, parquet) as conn:
        assert conn.execute("SELECT x FROM t").fetchone() == (1,)
    with cache.connection("ds_a", 2, parquet):
        pass
    assert len(cache) == 1  # v1 evicted when v2 opened
    with cache.connection("ds_b", 1, parquet):
        pass
    with cache.connection("ds_c", 1, parquet):
        pass
    assert len(cache) == 2  # LRU cap
    cache.close()
