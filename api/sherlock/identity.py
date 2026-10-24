"""Cookie identity (TRD §3.1, App Flow §2): `sherlock_uid` → `users`, created on first request.

The token is 256 random bits sent as an HttpOnly, SameSite=Lax cookie with a one-year
expiry; only its sha256 is stored. Pure ASGI, so it also works for streaming responses (SSE).
"""

import secrets
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


def resolve_user(settings: Settings, token: str | None) -> tuple[User, str | None]:
    """Return the user for this token, creating one (and a new token) when it is missing or unknown."""
    conn = connect(settings)
    try:
        if token:
            user = users.get_by_token(conn, token)
            if user:
                return user, None
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

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(IDENTITY_PATH_PREFIX):
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        token = request.cookies.get(COOKIE_NAME)
        user, new_token = await anyio.to_thread.run_sync(resolve_user, self.settings, token)
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
