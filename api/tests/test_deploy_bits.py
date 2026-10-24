import sqlite3

from fastapi.testclient import TestClient

from sherlock.config import get_settings
from sherlock.main import create_app
from sherlock.storage_check import check_storage


def test_storage_check_counts_boots_and_verifies_sqlite_lock():
    settings = get_settings()
    first = check_storage(settings)
    assert first["writable"] is True
    assert first["sqlite_lock"] is True
    assert first["boots"] == 1
    second = check_storage(settings)  # a restart on the same volume
    assert second["boots"] == 2
    assert second["first_boot_at"] == first["first_boot_at"]


def test_storage_check_reports_an_unwritable_dir(monkeypatch, tmp_path):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    monkeypatch.setenv("DATA_DIR", str(blocker / "data"))
    get_settings.cache_clear()
    result = check_storage(get_settings())
    assert result["writable"] is False
    assert "error" in result


def test_healthz_includes_storage(client):
    body = client.get("/healthz").json()
    assert body["storage"]["writable"] is True
    assert body["storage"]["sqlite_lock"] is True
    assert body["ok"] is True


def test_serves_the_web_app_with_spa_fallback(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>Sherlock</title>")
    (dist / "assets" / "app.js").write_text("console.log('hi')")
    (tmp_path / "secret.txt").write_text("outside dist")
    monkeypatch.setenv("WEB_DIST_DIR", str(dist))
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        assert "Sherlock" in client.get("/").text
        assert client.get("/assets/app.js").text == "console.log('hi')"
        assert "Sherlock" in client.get("/datasets/ds_123").text  # client-side route
        assert "outside dist" not in client.get("/../secret.txt").text
        api_404 = client.get("/api/v1/nope")
        assert api_404.status_code == 404
        assert api_404.json()["error"]["code"] == "not_found"
        assert client.get("/healthz").json()["ok"] is True


def test_no_web_dir_means_no_catch_all(client):
    assert client.get("/").status_code == 404


def test_lock_db_is_separate_from_the_app_db():
    settings = get_settings()
    check_storage(settings)
    assert (settings.data_dir / ".lockcheck.db").exists()
    with sqlite3.connect(settings.data_dir / ".lockcheck.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0
