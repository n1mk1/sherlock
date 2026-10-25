"""Text helpers for model output: strip reasoning traces, pull out JSON."""

import json
import re
import unicodedata

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"```(?:json|python)?\s*\n?(.*?)```", re.DOTALL)
_DIGIT = re.compile(r"\d")


def strip_reasoning(text: str) -> str:
    """Remove <think>…</think> blocks (and an unterminated leading one) that reasoning models emit."""
    text = _THINK.sub("", text)
    if "</think>" in text.lower():
        text = text[text.lower().rindex("</think>") + len("</think>") :]
    return text.strip()


def extract_json(text: str) -> object:
    """Parse the first JSON object in a model reply, tolerating reasoning and code fences."""
    text = strip_reasoning(text)
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end < start:
        raise ValueError("no JSON object in model output")
    return json.loads(text[start : end + 1])


def extract_code(text: str) -> str:
    """Return the first fenced code block, or the whole reply without reasoning."""
    text = strip_reasoning(text)
    fenced = _FENCE.search(text)
    return (fenced.group(1) if fenced else text).strip()


def has_digits(text: str) -> bool:
    """The narrator's no-digits rule (TRD §7.4): numbers in prose must be chips. Any Unicode number
    counts, not only 0-9: "²", "½", "①" and "Ⅻ" read as numbers too."""
    return bool(_DIGIT.search(text)) or any(unicodedata.category(ch).startswith("N") for ch in text)
