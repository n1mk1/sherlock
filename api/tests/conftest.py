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
    # No job workers: an upload's profile job (and its typing step) would race the test's own commits.
    # Tests of jobs opt in with the run_jobs fixture.
    "JOB_WORKERS": "0",
    # The sample goes through the live pipeline in tests; test_sample_seed.py turns the seed on.
    "SAMPLE_SEED_DIR": "off",
}


@pytest.fixture(autouse=True)
def test_env(monkeypatch, tmp_path):
    for key, value in TEST_MODELS.items():
        monkeypatch.setenv(key, value)
    # Never reach Token Factory from unit tests.
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.setenv("LLM_API_KEY", "")
    # ... nor Tavily: web features run on a fake transport or fail soft (TRD §3.6).
    monkeypatch.setenv("TAVILY_API_KEY", "")
    # Each test gets its own data dir and SQLite file.
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'data' / 'sherlock.db').as_posix()}")
    # ... and its own sandbox temp root: the default, <system temp>/sherlock-sandbox, is shared with every
    # other Sherlock process on the machine, so "temp dirs removed" checks would see their workers.
    monkeypatch.setenv("SANDBOX_TMP", str(tmp_path / "sandbox"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def run_jobs(monkeypatch):
    monkeypatch.setenv("JOB_WORKERS", "4")
    get_settings.cache_clear()


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def closed_breakers():
    """The model client's circuit breakers are process-wide (TRD §3.5): a test's failures mustn't send
    the next test's Super calls to Ultra."""
    from sherlock.llm.client import reset_breakers

    reset_breakers()
    yield
    reset_breakers()
