from fastapi import Depends
from fastapi.testclient import TestClient

from sherlock.ratelimit import LIMITS_PER_MINUTE, RateLimiter, llm_rate_limit


def test_limits_match_trd():
    assert LIMITS_PER_MINUTE == {"read": 600, "mutate": 60, "llm": 10}


def test_sliding_window_blocks_then_frees_a_slot():
    now = [0.0]
    limiter = RateLimiter({"read": 2, "mutate": 1, "llm": 1}, window_s=60, clock=lambda: now[0])
    assert limiter.hit("u1", "read") is None
    now[0] = 10
    assert limiter.hit("u1", "read") is None
    now[0] = 20
    assert limiter.hit("u1", "read") == 40  # the first hit expires at t=60
    assert limiter.hit("u2", "read") is None  # per user
    assert limiter.hit("u1", "mutate") is None  # per bucket
    now[0] = 60
    assert limiter.hit("u1", "read") is None


def test_api_returns_429_with_retry_after(app):
    app.state.rate_limiter = RateLimiter({"read": 2, "mutate": 1, "llm": 1})
    with TestClient(app) as client:
        assert client.get("/api/v1/me").status_code == 200
        assert client.get("/api/v1/me").status_code == 200
        res = client.get("/api/v1/me")
        assert res.status_code == 429
        assert res.json()["error"]["code"] == "rate_limited"
        assert 1 <= int(res.headers["retry-after"]) <= 60
        # Mutations have their own bucket.
        assert client.put("/api/v1/me/settings", json={"theme": "dark"}).status_code == 200
        assert client.put("/api/v1/me/settings", json={"theme": "dark"}).status_code == 429


def test_llm_bucket_applies_on_top(app):
    app.state.rate_limiter = RateLimiter({"read": 100, "mutate": 100, "llm": 1})

    @app.post("/api/v1/_test_llm", dependencies=[Depends(llm_rate_limit)])
    def _llm():
        return {"ok": True}

    with TestClient(app) as client:
        assert client.post("/api/v1/_test_llm").status_code == 200
        assert client.post("/api/v1/_test_llm").status_code == 429
