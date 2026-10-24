"""Per-user rate limits (TRD §15): 600 reads, 60 mutations and 10 LLM-bearing requests per minute.

In-memory sliding windows, which is correct because the API runs as exactly one process
(TRD §3.1). Over the limit → `429 rate_limited` with `Retry-After`.
"""

import math
import time
from collections import defaultdict, deque
from collections.abc import Callable

from fastapi import Depends, Request

from sherlock.db.users import User
from sherlock.errors import ApiError
from sherlock.identity import current_user

LIMITS_PER_MINUTE = {"read": 600, "mutate": 60, "llm": 10}
WINDOW_S = 60.0
READ_METHODS = {"GET", "HEAD", "OPTIONS"}


class RateLimiter:
    def __init__(
        self,
        limits: dict[str, int] | None = None,
        window_s: float = WINDOW_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limits = limits or dict(LIMITS_PER_MINUTE)
        self.window_s = window_s
        self.clock = clock
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def hit(self, user_id: str, bucket: str) -> float | None:
        """Record a request. Returns None if allowed, else seconds until a slot frees up."""
        now = self.clock()
        hits = self._hits[(user_id, bucket)]
        while hits and now - hits[0] >= self.window_s:
            hits.popleft()
        if len(hits) >= self.limits[bucket]:
            return self.window_s - (now - hits[0])
        hits.append(now)
        return None


def _enforce(request: Request, user: User, bucket: str) -> None:
    retry_after = request.app.state.rate_limiter.hit(user.id, bucket)
    if retry_after is not None:
        seconds = max(1, math.ceil(retry_after))
        raise ApiError(
            429, "rate_limited",
            f"Too many requests. Try again in {seconds} seconds.",
            headers={"Retry-After": str(seconds)},
        )


def rate_limit(request: Request, user: User = Depends(current_user)) -> None:
    """Router-wide dependency: reads and mutations by HTTP method."""
    _enforce(request, user, "read" if request.method in READ_METHODS else "mutate")


def llm_rate_limit(request: Request, user: User = Depends(current_user)) -> None:
    """Added to routes that call the model (chat, clean, stories…), on top of rate_limit."""
    _enforce(request, user, "llm")
