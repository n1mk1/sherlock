"""Text helpers: data blocks for prompts (TRD §3.5), and for model output, strip reasoning traces and pull out JSON."""

import json
import re
import unicodedata

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"```(?:json|python)?\s*\n?(.*?)```", re.DOTALL)
_DIGIT = re.compile(r"\d")
# Any spelling of a data tag a cell, a name or a web page could carry: "</data>", "</DATA >", "< /data>", "<data x>".
DATA_TAG = re.compile(r"<\s*/?\s*data\b[^>]*>", re.I)


def escape_data(text) -> str:
    """Text for inside a data block: every data tag in it is defused (its angle brackets become ‹ ›), so
    nothing a value holds can close the block or open another (TRD §3.5 prompt hygiene)."""
    return DATA_TAG.sub(lambda m: m.group(0).replace("<", "‹").replace(">", "›"), str(text))


def fence(content) -> str:
    """Cell values, names and user text always go inside a data block (TRD §3.5)."""
    return f"<data>\n{escape_data(content)}\n</data>"


def strip_reasoning(text: str) -> str:
    """Remove the <think>…</think> blocks reasoning models emit, a lone closing tag (the opening one was
    never sent) and an unterminated one (a reply cut off mid-reasoning: everything after <think> goes)."""
    text = _THINK.sub("", text)
    if "</think>" in text.lower():
        text = text[text.lower().rindex("</think>") + len("</think>") :]
    if "<think>" in text.lower():
        text = text[: text.lower().index("<think>")]
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


def has_digits(text: str) -> bool:
    """The narrator's no-digits rule (TRD §7.4): numbers in prose must be chips. Any Unicode number
    counts, not only 0-9: "²", "½", "①" and "Ⅻ" read as numbers too."""
    return bool(_DIGIT.search(text)) or any(unicodedata.category(ch).startswith("N") for ch in text)
