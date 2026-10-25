import pytest

from sherlock.config import Settings
from sherlock.llm.models import ModelConfigError, pick_roles, validate_model_roles
from sherlock.llm.text import extract_code, extract_json, has_digits, strip_reasoning


def settings(**overrides) -> Settings:
    base = {
        "model_large": "nvidia/nemotron-3-ultra",
        "model_medium": "nvidia/nemotron-3-super",
        "model_small": "nvidia/nemotron-3-nano",
        "model_embed": "",
        "nvidia_embed_models": "",
    }
    return Settings(_env_file=None, **(base | overrides))


def test_validate_accepts_nemotron_roles_and_empty_embed():
    validate_model_roles(settings())


def test_validate_rejects_empty_or_non_nemotron_role():
    with pytest.raises(ModelConfigError, match="MODEL_SMALL"):
        validate_model_roles(settings(model_small=""))
    with pytest.raises(ModelConfigError, match="MODEL_LARGE"):
        validate_model_roles(settings(model_large="deepseek-ai/DeepSeek-V3"))


def test_validate_embed_must_be_allowlisted():
    with pytest.raises(ModelConfigError, match="MODEL_EMBED"):
        validate_model_roles(settings(model_embed="BAAI/bge-m3"))
    validate_model_roles(
        settings(model_embed="nvidia/nv-embed-v2", nvidia_embed_models="nvidia/nv-embed-v2")
    )


def test_validate_embed_allowlist_cannot_admit_a_non_nvidia_model():
    # CLAUDE.md rule 2: listing a model in NVIDIA_EMBED_MODELS doesn't make it NVIDIA.
    with pytest.raises(ModelConfigError, match="not an NVIDIA embedding model"):
        validate_model_roles(settings(model_embed="BAAI/bge-m3", nvidia_embed_models="BAAI/bge-m3"))


def test_pick_roles_prefers_nemotron_3_tiers():
    catalog = [
        "meta-llama/Llama-3.3-70B-Instruct",
        "nvidia/Llama-3_1-Nemotron-Ultra-253B-v1",
        "nvidia/NVIDIA-Nemotron-3-Ultra-550B",
        "nvidia/NVIDIA-Nemotron-3-Super-120B",
        "nvidia/NVIDIA-Nemotron-3-Nano-30B",
        "nvidia/nv-embedqa-e5-v5",
        "BAAI/bge-m3",
    ]
    assert pick_roles(catalog) == {
        "large": "nvidia/NVIDIA-Nemotron-3-Ultra-550B",
        "medium": "nvidia/NVIDIA-Nemotron-3-Super-120B",
        "small": "nvidia/NVIDIA-Nemotron-3-Nano-30B",
        "embed": "nvidia/nv-embedqa-e5-v5",
    }


def test_pick_roles_leaves_missing_tiers_empty():
    assert pick_roles(["nvidia/Nemotron-3-Nano-30B"]) == {
        "large": "",
        "medium": "",
        "small": "nvidia/Nemotron-3-Nano-30B",
        "embed": "",
    }


def test_strip_reasoning_and_extract_json():
    raw = '<think>the user wants {"x": 2}</think>\n```json\n{"cause": "typo", "risk": "low"}\n```'
    assert strip_reasoning(raw).startswith("```json")
    assert extract_json(raw) == {"cause": "typo", "risk": "low"}
    # Some servers drop the opening tag and only send the closing one.
    assert extract_json('reasoning here</think>{"a": 1}') == {"a": 1}


def test_extract_code_and_no_digits_rule():
    assert extract_code("Here:\n```python\nresult = df.head()\n```") == "result = df.head()"
    assert has_digits("Fares rose by 12%")
    assert not has_digits("Fares rose sharply")
