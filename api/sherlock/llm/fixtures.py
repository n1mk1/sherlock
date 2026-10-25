"""Recorded model responses (Implementation Plan §1): tests and `LLM_MOCK` runs answer from these
instead of calling Token Factory, and `LLM_RECORD` writes them from live calls.

A fixture file is a JSON list of entries:
`{"purpose", "match": [substrings of the prompt], "content", "tool_calls", "prompt_tokens", "completion_tokens"}`.
A call looks at the entries whose purpose matches and whose `match` strings all occur in the prompt,
keeps the most specific ones (the most `match` strings), and takes the first unused of those; once
all of them are used, the last one repeats. `LLM_MOCK` names a file or a
directory of `*.json` files.
"""

import json
import threading
from pathlib import Path

from sherlock.llm.client import Transport


class FixtureMiss(Exception):
    pass


def _prompt(messages: list[dict]) -> str:
    return "\n".join(str(m.get("content") or "") for m in messages)


class FixtureTransport(Transport):
    def __init__(self, entries: list[dict]) -> None:
        self.entries = entries
        self.used: set[int] = set()
        self.calls: list[dict] = []  # what was asked, for test assertions
        self._lock = threading.Lock()

    @classmethod
    def load(cls, path: str | Path) -> "FixtureTransport":
        path = Path(path)
        files = sorted(path.glob("*.json")) if path.is_dir() else [path]
        entries: list[dict] = []
        for f in files:
            entries += json.loads(f.read_text(encoding="utf-8"))
        return cls(entries)

    def create(self, *, model, messages, timeout, purpose, **kwargs) -> dict:
        prompt = _prompt(messages)
        with self._lock:
            self.calls.append({"purpose": purpose, "model": model, "prompt": prompt, **kwargs})
            matches = [
                i for i, e in enumerate(self.entries)
                if e["purpose"] == purpose and all(m in prompt for m in e.get("match", []))
            ]
            if not matches:
                raise FixtureMiss(f"no recorded response for purpose {purpose!r}")
            most = max(len(self.entries[i].get("match", [])) for i in matches)
            matches = [i for i in matches if len(self.entries[i].get("match", [])) == most]
            unused = [i for i in matches if i not in self.used]
            index = unused[0] if unused else matches[-1]
            self.used.add(index)
        e = self.entries[index]
        content = e["content"] if isinstance(e["content"], str) else json.dumps(e["content"])
        return {
            "content": content,
            "tool_calls": e.get("tool_calls", []),
            "prompt_tokens": e.get("prompt_tokens", 100),
            "completion_tokens": e.get("completion_tokens", 50),
        }


class RecordingTransport(Transport):
    """Wraps a live transport and appends every reply to a fixture file (for `LLM_RECORD`)."""

    def __init__(self, inner: Transport, path: str | Path) -> None:
        self.inner = inner
        self.path = Path(path)
        self._lock = threading.Lock()

    def create(self, *, model, messages, timeout, purpose, **kwargs) -> dict:
        out = self.inner.create(model=model, messages=messages, timeout=timeout, purpose=purpose, **kwargs)
        with self._lock:
            entries = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else []
            entries.append({"purpose": purpose, "match": [], "model": model, **out})
            self.path.write_text(json.dumps(entries, indent=1, ensure_ascii=False), encoding="utf-8")
        return out
