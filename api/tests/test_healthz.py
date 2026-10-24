import pytest
from fastapi.testclient import TestClient

from sherlock.config import Settings, get_settings
from sherlock.llm.models import ModelConfigError
from sherlock.main import create_app


def test_healthz_reports_ok_llm_and_model_roles():
    app = create_app()
    app.state.llm_reachability.check = lambda: True
    with TestClient(app) as client:
        res = client.get("/healthz")

    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["llm"] == {"reachable": True}
    assert set(body["models"]) == {"large", "medium", "small", "embed"}
    assert body["models"]["large"] == "nvidia/nemotron-test-ultra"


def test_healthz_reports_unreachable_llm_without_credentials():
    with TestClient(create_app()) as client:
        assert client.get("/healthz").json()["llm"] == {"reachable": False}


def test_startup_fails_on_a_non_nvidia_role(monkeypatch):
    monkeypatch.setenv("MODEL_MEDIUM", "meta-llama/Llama-3.3-70B-Instruct")
    get_settings.cache_clear()
    with pytest.raises(ModelConfigError, match="MODEL_MEDIUM"):
        with TestClient(create_app()):
            pass


def test_settings_defaults_match_trd():
    s = Settings(_env_file=None)
    assert str(s.data_dir).replace("\\", "/") == "/data"
    assert s.llm_tools_mode == "json"
    assert s.job_backend == "local"
    assert (s.max_upload_mb, s.max_columns, s.max_rows) == (50, 1000, 2_000_000)
    assert s.notebook_pins.startswith("pandas==2.2.3,")
