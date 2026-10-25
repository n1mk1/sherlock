"""The JSON repair loop (TRD §3.5): validate a structured reply; on failure, one repair call sends
the validation error back and asks for corrected JSON."""

import json
from collections.abc import Callable
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from sherlock.llm.text import extract_json

T = TypeVar("T", bound=BaseModel)
MAX_ECHO_CHARS = 8000


def parse(content: str, schema: type[T], validate: Callable[[T], None] | None = None) -> tuple[T | None, str | None]:
    """(value, None) when the reply is valid, else (None, a one-line error for the repair call)."""
    try:
        value = schema.model_validate(extract_json(content))
        if validate is not None:
            validate(value)
        return value, None
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        return None, f"{exc.error_count()} error(s); first at {where or 'top level'}: {first['msg']}"
    except (ValueError, json.JSONDecodeError) as exc:
        return None, str(exc).splitlines()[0][:300]


def repair_messages(messages: list[dict], reply: str, error: str) -> list[dict]:
    return [
        *messages,
        {"role": "assistant", "content": reply[:MAX_ECHO_CHARS]},
        {"role": "user", "content": (
            f"That reply failed validation: {error}. Reply again with corrected JSON only, "
            "matching the schema exactly.")},
    ]
