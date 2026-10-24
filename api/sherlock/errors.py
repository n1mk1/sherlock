"""Error envelope and request IDs (TRD §3.1, §4).

Every error is `{"error": {"code", "message", "request_id"}}`; every response carries
`X-Request-ID`.
"""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from sherlock.db.util import new_id

ERROR_CODES = (
    "not_found", "invalid", "too_large", "budget_exceeded", "conflict",
    "llm_unavailable", "rate_limited", "internal",
)
_STATUS_CODES = {404: "not_found", 409: "conflict", 413: "too_large", 429: "rate_limited"}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, headers: dict | None = None):
        assert code in ERROR_CODES, code
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers or {}


def not_found(what: str = "Not found") -> ApiError:
    return ApiError(404, "not_found", what)


class RequestIdMiddleware:
    """Assigns `req_<ulid>` to scope state and echoes it as `X-Request-ID`."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = new_id("req")
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).append("x-request-id", request_id)
            await send(message)

        await self.app(scope, receive, send_with_id)


def request_id_of(request: Request) -> str:
    return getattr(request.state, "request_id", "")


def error_response(request: Request, status: int, code: str, message: str, headers=None):
    body = {"error": {"code": code, "message": message, "request_id": request_id_of(request)}}
    return JSONResponse(body, status_code=status, headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return error_response(request, exc.status, exc.code, exc.message, exc.headers)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        code = _STATUS_CODES.get(exc.status_code, "internal" if exc.status_code >= 500 else "invalid")
        return error_response(request, exc.status_code, code, str(exc.detail), exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", ()))
        return error_response(request, 422, "invalid", f"{where}: {first.get('msg', 'invalid request')}")

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        return error_response(request, 500, "internal", "Something went wrong on our side.")
