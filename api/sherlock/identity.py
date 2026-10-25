"""Cookie identity (TRD §3.1, App Flow §2): `sherlock_uid` → `users`, created on first request.

The token is 256 random bits sent as an HttpOnly, SameSite=Lax cookie with a one-year
expiry; only its sha256 is stored. Pure ASGI, so it also works for streaming responses (SSE).

New users are capped per client IP (`NEW_USERS_PER_IP_HOUR`, TRD §15): a client that drops its
cookie would otherwise get fresh per-user limits and budgets on every request. The IP is the
`X-Forwarded-For` entry just before the ones the host's own proxies appended (`TRUSTED_PROXY_HOPS`,
1 on Render; a client can forge the entries before it), else the socket's peer. The window is in memory, which is right for the one API process (TRD §3.1).
"""

import hashlib
import json
import logging
import secrets
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from http.cookies import SimpleCookie

import anyio
from fastapi import Request
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from sherlock.config import Settings
from sherlock.db import users
from sherlock.db.connection import connect
from sherlock.db.users import User

COOKIE_NAME = "sherlock_uid"
COOKIE_MAX_AGE_S = 365 * 24 * 3600
IDENTITY_PATH_PREFIX = "/api/"
NEW_USER_WINDOW_S = 3600.0
log = logging.getLogger("sherlock.identity")


class TooManyNewUsers(Exception):
    def __init__(self, retry_after: float) -> None:
        self.retry_after = retry_after


class NewUserLimiter:
    """Sliding one-hour window of new users per client IP."""

    def __init__(self, per_hour: int, window_s: float = NEW_USER_WINDOW_S, clock: Callable[[], float] = time.monotonic):
        self.per_hour = per_hour
        self.window_s = window_s
        self.clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def admit(self, ip: str) -> None:
        """Count a new user for this IP, or raise TooManyNewUsers."""
        if self.per_hour <= 0:
            return
        with self._lock:
            now = self.clock()
            hits = self._hits[ip]
            while hits and now - hits[0] >= self.window_s:
                hits.popleft()
            if len(hits) >= self.per_hour:
                raise TooManyNewUsers(self.window_s - (now - hits[0]))
            hits.append(now)
            if len(self._hits) > 10_000:  # keep the table small
                for key in [k for k, v in self._hits.items() if not v or now - v[-1] >= self.window_s]:
                    del self._hits[key]


def client_ip(scope: Scope, trusted_proxies: int = 1) -> str:
    """The client's IP: the `X-Forwarded-For` entry just before the `trusted_proxies` entries the host's
    own proxies appended. On Render a plain request arrives as `client, render-proxy` (checked live,
    2026-10-25), so it's the second-to-last; entries a client sends itself come before it and are ignored."""
    hops: list[str] = []
    for name, value in scope.get("headers") or []:
        if name == b"x-forwarded-for":
            hops += [h.strip() for h in value.decode("latin-1").split(",") if h.strip()]
    if hops:
        return hops[-(trusted_proxies + 1)] if len(hops) > trusted_proxies else hops[0]
    client = scope.get("client")
    return client[0] if client else "unknown"


def resolve_user(settings: Settings, token: str | None, admit: Callable[[], None] = lambda: None) -> tuple[User, str | None]:
    """Return the user for this token, creating one (and a new token) when it is missing or unknown.
    `admit` runs before a user is created and may raise TooManyNewUsers."""
    conn = connect(settings)
    try:
        if token:
            user = users.get_by_token(conn, token)
            if user:
                return user, None
        admit()
        new_token = secrets.token_urlsafe(32)  # 256 bits
        return users.create(conn, new_token), new_token
    finally:
        conn.close()


def cookie_header(token: str, secure: bool) -> str:
    cookie = SimpleCookie()
    cookie[COOKIE_NAME] = token
    morsel = cookie[COOKIE_NAME]
    morsel["path"] = "/"
    morsel["max-age"] = COOKIE_MAX_AGE_S
    morsel["httponly"] = True
    morsel["samesite"] = "Lax"
    if secure:
        morsel["secure"] = True
    return morsel.OutputString()


def _is_https(request: Request) -> bool:
    forwarded = request.headers.get("x-forwarded-proto", "")
    return request.url.scheme == "https" or forwarded.split(",")[0].strip() == "https"


class IdentityMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings
        self.new_users = NewUserLimiter(settings.new_users_per_ip_hour)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(IDENTITY_PATH_PREFIX):
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        token = request.cookies.get(COOKIE_NAME)
        ip = client_ip(scope, self.settings.trusted_proxy_hops)

        def admit() -> None:
            self.new_users.admit(ip)
            # How many hops the proxy sends, to check which X-Forwarded-For entry is the client's.
            # The IP itself is only logged as a short hash.
            hops = sum(len(v.split(b",")) for k, v in scope.get("headers") or [] if k == b"x-forwarded-for")
            log.info("new user: ip %s, %d forwarded hop(s)", hashlib.sha256(ip.encode()).hexdigest()[:8], hops)

        try:
            user, new_token = await anyio.to_thread.run_sync(resolve_user, self.settings, token, admit)
        except TooManyNewUsers as exc:
            seconds = max(1, int(exc.retry_after) + 1)
            body = json.dumps({"error": {
                "code": "rate_limited", "request_id": (scope.get("state") or {}).get("request_id", ""),
                "message": f"Too many new visitors from your network. Try again in {seconds // 60 + 1} minutes."}})
            await send({"type": "http.response.start", "status": 429, "headers": [
                (b"content-type", b"application/json"), (b"retry-after", str(seconds).encode())]})
            await send({"type": "http.response.body", "body": body.encode()})
            return
        scope.setdefault("state", {})["user"] = user
        secure = _is_https(request)

        async def send_with_cookie(message: Message) -> None:
            if new_token and message["type"] == "http.response.start":
                MutableHeaders(scope=message).append("set-cookie", cookie_header(new_token, secure))
            await send(message)

        await self.app(scope, receive, send_with_cookie)


def current_user(request: Request) -> User:
    """Dependency for every /api/v1 route: the user resolved by IdentityMiddleware."""
    return request.state.user
