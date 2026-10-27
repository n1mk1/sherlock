import logging

import pytest
from fastapi.testclient import TestClient

from sherlock.config import Settings, get_settings
from sherlock.db.migrate import available
from sherlock.llm.models import ModelConfigError
from sherlock.main import create_app


def test_healthz_reports_db_llm_and_model_roles(app):
    app.state.llm_reachability.check = lambda: True
    with TestClient(app) as client:
        res = client.get("/healthz")

    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["db"] == {"ok": True, "schema_version": available()[-1][0]}  # the newest migration file
    assert body["llm"] == {"reachable": True}
    assert set(body["models"]) == {"large", "medium", "small", "embed"}
    assert body["models"]["large"] == "nvidia/nemotron-test-ultra"
    assert res.headers["x-request-id"].startswith("req_")
    assert "set-cookie" not in res.headers  # identity applies to /api/ only


def test_healthz_reports_unreachable_llm_without_credentials(client):
    assert client.get("/healthz").json()["llm"] == {"reachable": False}


def test_healthz_reports_the_deployed_commit(monkeypatch):
    monkeypatch.setenv("RENDER_GIT_COMMIT", "fb4406f1e2d3c4b5a6978877665544332211aabb")
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        assert client.get("/healthz").json()["commit"] == "fb4406f1e2d3"


def test_log_level_applies_to_the_app_loggers(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "warning")
    get_settings.cache_clear()
    try:
        create_app()
        assert logging.getLogger("sherlock").level == logging.WARNING
    finally:
        logging.getLogger("sherlock").setLevel(logging.INFO)


def test_startup_fails_on_a_non_nvidia_role(monkeypatch):
    monkeypatch.setenv("MODEL_MEDIUM", "meta-llama/Llama-3.3-70B-Instruct")
    get_settings.cache_clear()
    with pytest.raises(ModelConfigError, match="MODEL_MEDIUM"):
        with TestClient(create_app()):
            pass


def test_settings_defaults_match_trd(monkeypatch):
    monkeypatch.delenv("DATA_DIR")
    monkeypatch.delenv("DATABASE_URL")
    s = Settings(_env_file=None)
    assert s.database_url == "sqlite:////data/sherlock.db"
    assert str(s.data_dir).replace("\\", "/") == "/data"
    assert s.llm_tools_mode == "json"
    assert (s.max_upload_mb, s.max_columns, s.max_rows) == (50, 1000, 2_000_000)
    assert s.notebook_pins.startswith("pandas==2.2.3,")
