"""Recorded Tavily responses (TRD §3.6, §14): tests and the offline `sherlock eval web` answer from these
instead of calling Tavily, and every request is captured so a test can check what would have gone out.

A fixture file is a JSON list of entries `{"kind", "match": [substrings of the request], "response"}`, or
`{"kind", "match", "error": "timeout" | "failed"}` to fail. A request takes, among the entries of its kind
whose `match` strings all occur in its values (lower-cased; a list as JSON), the most specific one. With no match it fails
like a 5xx, so a fixture run never reaches the network and still fails soft.
"""

import json
import threading
from pathlib import Path

from sherlock.web.client import WebFailed, WebTimeout, WebTransport

# The offline eval's recorded responses (`sherlock eval web`, TRD §14).
FIXTURES_DIR = Path(__file__).resolve().parents[2] / "samples" / "eval" / "web"


class WebFixtureTransport(WebTransport):
    def __init__(self, entries: list[dict]) -> None:
        self.entries = entries
        self.calls: list[dict] = []  # {kind, params, timeout}: everything that would have been sent
        self._lock = threading.Lock()

    @classmethod
    def load(cls, path: str | Path = FIXTURES_DIR) -> "WebFixtureTransport":
        path = Path(path)
        files = sorted(path.glob("*.json")) if path.is_dir() else [path]
        entries: list[dict] = []
        for f in files:
            entries += json.loads(f.read_text(encoding="utf-8"))
        return cls(entries)

    def call(self, kind, params, timeout) -> dict:
        text = " ".join(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False) for v in params.values()).lower()
        with self._lock:
            self.calls.append({"kind": kind, "params": params, "timeout": timeout})
        found = [e for e in self.entries if e["kind"] == kind and all(m.lower() in text for m in e.get("match", []))]
        if not found:
            raise WebFailed(f"no recorded {kind} response")
        entry = max(found, key=lambda e: len(e.get("match", [])))
        if entry.get("error") == "timeout":
            raise WebTimeout("recorded timeout")
        if entry.get("error"):
            raise WebFailed(f"recorded failure: {entry['error']}")
        return json.loads(json.dumps(entry["response"]))  # a copy, so a caller can't change the fixture


class FailingTransport(WebTransport):
    """Every call times out or fails (the fail-soft checks)."""

    def __init__(self, how: str = "failed") -> None:
        self.how = how
        self.calls: list[dict] = []

    def call(self, kind, params, timeout) -> dict:
        self.calls.append({"kind": kind, "params": params, "timeout": timeout})
        if self.how == "timeout":
            raise WebTimeout("timed out")
        raise WebFailed("HTTP 502")
