import pytest
from fastapi.testclient import TestClient

from sherlock.config import get_settings
from sherlock.main import create_app

# Valid NVIDIA roles so the startup check passes without a real .env (CI has none).
TEST_MODELS = {
    "MODEL_LARGE": "nvidia/nemotron-test-ultra",
    "MODEL_MEDIUM": "nvidia/nemotron-test-super",
    "MODEL_SMALL": "nvidia/nemotron-test-nano",
    "MODEL_EMBED": "",
    "NVIDIA_EMBED_MODELS": "",
}


@pytest.fixture(autouse=True)
def test_env(monkeypatch, tmp_path):
    for key, value in TEST_MODELS.items():
        monkeypatch.setenv(key, value)
    # Never reach Token Factory from unit tests.
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.setenv("LLM_API_KEY", "")
    # Each test gets its own data dir and SQLite file.
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'data' / 'sherlock.db').as_posix()}")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c
