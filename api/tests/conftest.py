import pytest

from sherlock.config import get_settings

# Valid NVIDIA roles so the startup check passes without a real .env (CI has none).
TEST_MODELS = {
    "MODEL_LARGE": "nvidia/nemotron-test-ultra",
    "MODEL_MEDIUM": "nvidia/nemotron-test-super",
    "MODEL_SMALL": "nvidia/nemotron-test-nano",
    "MODEL_EMBED": "",
    "NVIDIA_EMBED_MODELS": "",
}


@pytest.fixture(autouse=True)
def test_env(monkeypatch):
    for key, value in TEST_MODELS.items():
        monkeypatch.setenv(key, value)
    # Never reach Token Factory from unit tests.
    monkeypatch.setenv("LLM_BASE_URL", "")
    monkeypatch.setenv("LLM_API_KEY", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
