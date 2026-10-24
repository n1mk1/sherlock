from fastapi.testclient import TestClient

from sherlock.config import Settings, get_settings
from sherlock.main import create_app


def test_healthz_reports_ok_and_model_roles(monkeypatch):
    monkeypatch.setenv("MODEL_LARGE", "nvidia/nemotron-test-ultra")
    get_settings.cache_clear()
    client = TestClient(create_app())

    res = client.get("/healthz")

    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert set(body["models"]) == {"large", "medium", "small", "embed"}
    assert body["models"]["large"] == "nvidia/nemotron-test-ultra"
    get_settings.cache_clear()


def test_settings_defaults_match_trd():
    s = Settings(_env_file=None)
    assert str(s.data_dir).replace("\\", "/") == "/data"
    assert s.llm_tools_mode == "json"
    assert s.job_backend == "local"
    assert (s.max_upload_mb, s.max_columns, s.max_rows) == (50, 1000, 2_000_000)
    assert s.notebook_pins.startswith("pandas==2.2.3,")
