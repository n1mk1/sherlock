"""The web client (TRD §3.6): Tavily's `search`, `extract` and `map`, for retrieval only.

Tavily's own model never writes text a user reads (CLAUDE.md Rule 2), so `research()` and
`include_answer` are never used: every parameter the client sends is fixed here, and a caller chooses
only the query (or URL), the topic and a time range. What goes out is built by the caller from the
user's own words and column names, never from cell values (`agent/web.py` checks it).

Every web feature fails soft. No key, `WEB_SEARCH=off`, the hourly limit, too little time left before
the call's deadline, a timeout, a 4xx or a 5xx: the call raises `WebUnavailable` with one line the
answer shows instead, and the rest of the answer goes on. Nothing here raises anything else.

Responses are cached for 24 h in `web_cache` (purged by the purge job), and each call, cached or not,
is an `llm_calls` row with `role = 'web'`, no tokens (so no token budget counts it), `cached` and the
number of `results`, so receipts and `sherlock llm stats` show it.
"""

import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sherlock.config import Settings
from sherlock.db.connection import connect
from sherlock.db.util import now_iso
from sherlock.llm.client import CallScope, gate

log = logging.getLogger("sherlock.web")

KINDS = ("search", "extract", "map")
MODELS = {"search": "tavily-search", "extract": "tavily-extract", "map": "tavily-map"}
CACHE_TTL_S = 24 * 3600
RATE_WINDOW_S = 3600
CONCURRENCY = 4          # Tavily calls in flight at once, across the process (the same gate as the model roles)
MAX_QUERY_CHARS = 400    # Tavily's advice for a search query
MAX_URLS = 3
# A call needs at least this long before its deadline: Tavily's map takes a server-side timeout of 10 s or more.
MIN_TIMEOUT_S = {"search": 1.0, "extract": 1.0, "map": 10.0}

# The fixed parameters (TRD §3.6). Retrieval only: no answer, no raw pages, no images, no auto-tuning.
SEARCH = {"search_depth": "basic", "max_results": 5, "include_answer": False, "include_raw_content": False,
          "include_images": False, "auto_parameters": False}
EXTRACT = {"extract_depth": "basic", "format": "markdown", "chunks_per_source": 3, "include_images": False}
MAP = {"max_depth": 1, "max_breadth": 20, "limit": 20, "allow_external": False}
TOPICS = ("general", "news")
TIME_RANGES = ("day", "week", "month", "year")

# The one line an answer shows when the web part didn't happen (no digits: it's plain prose).
NOTES = {
    "off": "Web search isn't set up on this server, so I didn't look this up on the web.",
    "rate": "I've already searched the web a lot this hour, so I didn't search again.",
    "deadline": "There wasn't enough time left in this answer to search the web.",
    "timeout": "The web search took too long, so I left it out.",
    "failed": "The web search didn't work just now, so I left it out.",
}


class WebUnavailable(Exception):
    """The web call didn't happen or failed. `note` is the line the answer shows instead."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail

    @property
    def note(self) -> str:
        return NOTES[self.reason]


class WebTimeout(Exception):
    pass


class WebFailed(Exception):
    """A 4xx, a 5xx, a connection error or a reply that isn't JSON."""


class WebTransport:
    """Sends one Tavily request. The real one uses `tavily-python`; tests and the offline eval use fakes."""

    def call(self, kind: str, params: dict, timeout: float) -> dict:
        raise NotImplementedError


class TavilyTransport(WebTransport):
    def __init__(self, api_key: str) -> None:
        if not api_key:
            # tavily-python would run "keyless" without one; Sherlock never sends a request it wasn't given a key for.
            raise ValueError("TavilyTransport needs an API key")
        self.api_key = api_key
        self._client = None
        self._lock = threading.Lock()

    def call(self, kind, params, timeout) -> dict:
        import requests
        from tavily import TavilyClient
        from tavily.errors import TimeoutError as TavilyTimeout

        with self._lock:
            if self._client is None:
                self._client = TavilyClient(api_key=self.api_key, client_source="sherlock")
        method = {"search": self._client.search, "extract": self._client.extract, "map": self._client.map}[kind]
        try:
            return method(**params, timeout=timeout)
        except (TavilyTimeout, requests.Timeout) as exc:
            raise WebTimeout(str(exc)) from exc
        except requests.HTTPError as exc:
            status = getattr(exc.response, "status_code", None)
            raise WebFailed(f"HTTP {status}" if status else type(exc).__name__) from exc
        except Exception as exc:  # noqa: BLE001 - every other failure (4xx errors, connection, bad JSON) fails soft
            raise WebFailed(f"{type(exc).__name__}: {str(exc)[:200]}") from exc


@dataclass
class WebResponse:
    kind: str
    request: dict
    data: dict
    cached: bool
    latency_ms: int
    retrieved_at: str  # when Tavily returned it (a cache hit keeps the original time)
    notes: list[str] = field(default_factory=list)

    @property
    def results(self) -> list:
        return list(self.data.get("results") or [])

    @property
    def retrieved_on(self) -> str:
        return self.retrieved_at[:10]


def cache_key(kind: str, params: dict) -> str:
    return hashlib.sha1((kind + "\n" + json.dumps(params, sort_keys=True, ensure_ascii=False)).encode("utf-8")).hexdigest()


def _ago(seconds: float) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def make_transport(settings: Settings) -> WebTransport | None:
    """Recorded fixtures with `WEB_MOCK`, else the live transport when web search is on and a key is set,
    else None (every call fails soft)."""
    if settings.web_search != "on":
        return None
    if settings.web_mock:
        from sherlock.web.fixtures import WebFixtureTransport

        return WebFixtureTransport.load(settings.web_mock)
    if not settings.tavily_api_key:
        return None
    return TavilyTransport(settings.tavily_api_key)


class WebClient:
    def __init__(self, settings: Settings, transport: WebTransport | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.settings = settings
        # A transport passed in (tests, the offline eval) is used even without a key; WEB_SEARCH=off still wins.
        self.transport = transport if transport is not None else make_transport(settings)
        self.clock = clock

    @property
    def enabled(self) -> bool:
        return self.transport is not None and self.settings.web_search == "on"

    # --- the three calls ----------------------------------------------------------------------

    def search(self, query: str, *, scope: CallScope, purpose: str, topic: str = "general",
               time_range: str | None = None) -> WebResponse:
        query = " ".join(query.split())[:MAX_QUERY_CHARS]
        if not query:
            raise WebUnavailable("failed", "empty query")
        params = {"query": query, **SEARCH, "topic": topic if topic in TOPICS else "general"}
        if time_range in TIME_RANGES:
            params["time_range"] = time_range
        return self._call("search", params, scope, purpose)

    def extract(self, urls: list[str], *, query: str, scope: CallScope, purpose: str) -> WebResponse:
        urls = [u for u in dict.fromkeys(urls) if u][:MAX_URLS]
        if not urls:
            raise WebUnavailable("failed", "no URL")
        params = {"urls": urls, **EXTRACT, "query": " ".join(query.split())[:MAX_QUERY_CHARS]}
        return self._call("extract", params, scope, purpose)

    def map(self, url: str, *, instructions: str, scope: CallScope, purpose: str) -> WebResponse:
        params = {"url": url, **MAP, "instructions": " ".join(instructions.split())[:MAX_QUERY_CHARS]}
        return self._call("map", params, scope, purpose)

    # --- plumbing -----------------------------------------------------------------------------

    def _call(self, kind: str, params: dict, scope: CallScope, purpose: str) -> WebResponse:
        if not self.enabled:
            raise WebUnavailable("off")
        key = cache_key(kind, params)
        hit = self._cached(key)
        if hit is not None:
            data, created_at = hit
            self._record(scope, kind, purpose, 0, True, None, True, len(data.get("results") or []))
            return WebResponse(kind, params, data, True, 0, created_at)
        if self._over_limit(scope):
            raise WebUnavailable("rate")
        floor = MIN_TIMEOUT_S[kind]
        if self._left(scope) < floor:
            raise WebUnavailable("deadline")
        door = gate("web", CONCURRENCY)
        if not door.acquire(timeout=max(0.0, min(self._left(scope) - floor, self.settings.tavily_timeout_s))):
            raise WebUnavailable("deadline", "every web slot stayed busy")
        left = self._left(scope)  # waiting for a slot used some of it
        if left < floor:
            door.release()
            raise WebUnavailable("deadline", "no time left after waiting for a slot")
        timeout = max(floor, min(self.settings.tavily_timeout_s, left))
        t0 = self.clock()
        try:
            data = self.transport.call(kind, params, timeout)
            if not isinstance(data, dict):
                raise WebFailed("the reply isn't an object")
        except WebTimeout as exc:
            self._record(scope, kind, purpose, self._ms(t0), False, f"timeout: {exc}", False, None)
            raise WebUnavailable("timeout", str(exc)) from None
        except Exception as exc:  # noqa: BLE001 - WebFailed and anything a fake raises: fail soft
            self._record(scope, kind, purpose, self._ms(t0), False, str(exc), False, None)
            log.warning("web %s/%s failed: %s", kind, purpose, exc)
            raise WebUnavailable("failed", str(exc)) from None
        finally:
            door.release()
        latency = self._ms(t0)
        created = now_iso()
        self._store(key, kind, params, data, created)
        self._record(scope, kind, purpose, latency, True, None, False, len(data.get("results") or []))
        return WebResponse(kind, params, data, False, latency, created)

    def _left(self, scope: CallScope) -> float:
        return float("inf") if scope.deadline is None else scope.deadline - self.clock()

    def _ms(self, t0: float) -> int:
        return int((self.clock() - t0) * 1000)

    def _cached(self, key: str) -> tuple[dict, str] | None:
        db = connect(self.settings)
        try:
            row = db.execute("SELECT response_json, created_at FROM web_cache WHERE key = ? AND created_at >= ?",
                             (key, _ago(CACHE_TTL_S))).fetchone()
        finally:
            db.close()
        return (json.loads(row["response_json"]), row["created_at"]) if row else None

    def _store(self, key: str, kind: str, params: dict, data: dict, created: str) -> None:
        db = connect(self.settings)
        try:
            db.execute("INSERT INTO web_cache (key, kind, request_json, response_json, created_at) VALUES (?, ?, ?, ?, ?) "
                       "ON CONFLICT(key) DO UPDATE SET response_json = excluded.response_json, created_at = excluded.created_at",
                       (key, kind, json.dumps(params, ensure_ascii=False), json.dumps(data, ensure_ascii=False), created))
        finally:
            db.close()

    def _over_limit(self, scope: CallScope) -> bool:
        limit = self.settings.web_rate_limit
        if limit <= 0 or not scope.user_id:
            return False
        db = connect(self.settings)
        try:
            used = db.execute("SELECT count(*) FROM llm_calls WHERE role = 'web' AND cached = 0 AND user_id = ? AND created_at >= ?",
                              (scope.user_id, _ago(RATE_WINDOW_S))).fetchone()[0]
        finally:
            db.close()
        return used >= limit

    def _record(self, scope: CallScope, kind: str, purpose: str, latency_ms: int, ok: bool, error: str | None,
                cached: bool, results: int | None) -> None:
        db = connect(self.settings)
        try:
            db.execute(
                "INSERT INTO llm_calls (user_id, dataset_id, job_id, message_id, role, model, purpose, prompt_tokens, "
                "completion_tokens, latency_ms, ok, error, repaired, created_at, cached, results) "
                "VALUES (?, ?, ?, ?, 'web', ?, ?, NULL, NULL, ?, ?, ?, 0, ?, ?, ?)",
                (scope.user_id, scope.dataset_id, scope.job_id, scope.message_id, MODELS[kind], purpose, latency_ms,
                 int(ok), (error or "")[:500] or None, now_iso(), int(cached), results),
            )
        finally:
            db.close()
