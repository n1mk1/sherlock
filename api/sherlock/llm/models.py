"""Model-role rules (TRD §3.5): every role is an NVIDIA model on Token Factory."""

import re
import time

from openai import OpenAI

from sherlock.config import Settings

ROLE_TIERS = {"large": "ultra", "medium": "super", "small": "nano"}


class ModelConfigError(RuntimeError):
    """Raised at startup when a model role is not an allowed NVIDIA model."""


def embed_allowlist(settings: Settings) -> list[str]:
    return [m.strip() for m in settings.nvidia_embed_models.split(",") if m.strip()]


def validate_model_roles(settings: Settings) -> None:
    """Fail startup unless large/medium/small are Nemotron and embed is empty or an allowlisted NVIDIA model."""
    problems = []
    for role in ("large", "medium", "small"):
        model_id = settings.models[role]
        if "nemotron" not in model_id.lower():
            problems.append(f"MODEL_{role.upper()}={model_id!r} is not a Nemotron model")
    embed = settings.model_embed
    if embed and embed not in embed_allowlist(settings):
        problems.append(f"MODEL_EMBED={embed!r} is not listed in NVIDIA_EMBED_MODELS")
    elif embed and not is_nvidia_embed(embed):
        # The allowlist is configuration too, so it can't vouch for a non-NVIDIA model.
        problems.append(f"MODEL_EMBED={embed!r} is not an NVIDIA embedding model")
    if problems:
        raise ModelConfigError("; ".join(problems))


def is_nemotron_chat(model_id: str) -> bool:
    lowered = model_id.lower()
    return "nemotron" in lowered and "embed" not in lowered


def is_nvidia_embed(model_id: str) -> bool:
    lowered = model_id.lower()
    return "embed" in lowered and ("nvidia" in lowered or "nv-" in lowered or "nemotron" in lowered)


def _size_billions(model_id: str) -> float:
    match = re.search(r"(\d+(?:\.\d+)?)b\b", model_id.lower())
    return float(match.group(1)) if match else 0.0


def pick_roles(catalog_ids: list[str]) -> dict[str, str]:
    """Suggest the Nemotron 3 Ultra / Super / Nano IDs for large / medium / small.

    Prefers "nemotron-3" IDs, then the largest parameter count within a tier. A role is
    left empty when the catalog has no model of its tier; the smoke test reports it.
    """
    chat = [m for m in catalog_ids if is_nemotron_chat(m)]
    roles: dict[str, str] = {}
    for role, tier in ROLE_TIERS.items():
        tiered = [m for m in chat if tier in m.lower()]
        tiered.sort(key=lambda m: ("nemotron-3" in m.lower(), _size_billions(m)), reverse=True)
        roles[role] = tiered[0] if tiered else ""
    embeds = sorted(m for m in catalog_ids if is_nvidia_embed(m))
    roles["embed"] = embeds[0] if embeds else ""
    return roles


class LLMReachability:
    """Cached Token Factory reachability for /healthz (one models call per TTL)."""

    def __init__(self, settings: Settings, ttl_s: float = 60.0) -> None:
        self._settings = settings
        self._ttl_s = ttl_s
        self._checked_at = 0.0
        self._reachable = False

    def check(self) -> bool:
        now = time.monotonic()
        if self._checked_at and now - self._checked_at < self._ttl_s:
            return self._reachable
        self._reachable = self._probe()
        self._checked_at = now
        return self._reachable

    def _probe(self) -> bool:
        if not (self._settings.llm_base_url and self._settings.llm_api_key):
            return False
        try:
            client = OpenAI(
                base_url=self._settings.llm_base_url,
                api_key=self._settings.llm_api_key,
                timeout=5.0,
                max_retries=0,
            )
            client.models.list()
            return True
        except Exception:
            return False
