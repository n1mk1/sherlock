import pytest
from fastapi.testclient import TestClient

from sherlock.config import get_settings
from sherlock.db.connection import connect
from sherlock.db.users import hash_token
from sherlock.identity import COOKIE_NAME


def users_rows():
    conn = connect(get_settings())
    try:
        return conn.execute("SELECT id, cookie_token FROM users").fetchall()
    finally:
        conn.close()


def test_first_request_creates_user_and_sets_cookie(client):
    res = client.get("/api/v1/me")

    assert res.status_code == 200
    cookie = res.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE_NAME}=")
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie
    assert "Max-Age=31536000" in cookie
    assert "Path=/" in cookie
    assert "Secure" not in cookie  # plain http in tests

    token = client.cookies[COOKIE_NAME]
    assert len(token) >= 43  # 32 random bytes, base64url
    rows = users_rows()
    assert len(rows) == 1
    assert rows[0]["cookie_token"] == hash_token(token)  # only the hash is stored
    assert rows[0]["cookie_token"] != token
    assert res.json()["user_id"] == rows[0]["id"]


def test_same_cookie_keeps_the_same_user(client):
    first = client.get("/api/v1/me").json()["user_id"]
    res = client.get("/api/v1/me")
    assert res.json()["user_id"] == first
    assert "set-cookie" not in res.headers
    assert len(users_rows()) == 1


def test_unknown_cookie_gets_a_fresh_user(app):
    with TestClient(app, cookies={COOKIE_NAME: "forged-or-expired"}) as client:
        res = client.get("/api/v1/me")
    assert res.status_code == 200
    assert "set-cookie" in res.headers
    assert len(users_rows()) == 1


def test_two_browsers_are_two_users(app):
    with TestClient(app) as a, TestClient(app) as b:
        assert a.get("/api/v1/me").json()["user_id"] != b.get("/api/v1/me").json()["user_id"]


def test_secure_cookie_behind_https_proxy(client):
    res = client.get("/api/v1/me", headers={"x-forwarded-proto": "https"})
    assert "Secure" in res.headers["set-cookie"]


def test_new_users_are_capped_per_client_ip(monkeypatch):
    # Review Day 1 #1: a client that drops its cookie got a fresh user, and fresh budgets, on every request.
    from sherlock.main import create_app

    monkeypatch.setenv("NEW_USERS_PER_IP_HOUR", "3")
    get_settings.cache_clear()
    try:
        app = create_app()
        with TestClient(app) as c:
            # As on Render: the client's entry, then the host's proxy (TRUSTED_PROXY_HOPS = 1).
            hdr = {"X-Forwarded-For": "203.0.113.9, 10.0.0.1"}
            codes = []
            for _ in range(3):
                c.cookies.clear()
                codes.append(c.get("/api/v1/me", headers=hdr).status_code)
            c.cookies.clear()
            blocked = c.get("/api/v1/me", headers=hdr)
            assert codes == [200, 200, 200] and blocked.status_code == 429
            assert blocked.json()["error"]["code"] == "rate_limited" and int(blocked.headers["retry-after"]) > 0
            # A forged entry doesn't buy a new bucket, nor does another proxy node; another client has its own.
            c.cookies.clear()
            assert c.get("/api/v1/me", headers={"X-Forwarded-For": "1.1.1.1, 203.0.113.9, 10.0.0.2"}).status_code == 429
            c.cookies.clear()
            ok = c.get("/api/v1/me", headers={"X-Forwarded-For": "198.51.100.7, 10.0.0.1"})
            assert ok.status_code == 200
            # Someone who already has a cookie is never capped.
            assert c.get("/api/v1/me", headers=hdr).status_code == 200
    finally:
        get_settings.cache_clear()


def test_new_user_limiter_window():
    from sherlock.identity import NewUserLimiter, TooManyNewUsers

    now = [0.0]
    lim = NewUserLimiter(2, window_s=100, clock=lambda: now[0])
    lim.admit("a"), lim.admit("a")
    with pytest.raises(TooManyNewUsers):
        lim.admit("a")
    now[0] = 100.0
    lim.admit("a")  # the first two have left the window


def test_client_ip_skips_the_hosts_proxies():
    from sherlock.identity import client_ip

    def scope(xff=None):
        return {"headers": [(b"x-forwarded-for", xff.encode())] if xff else [], "client": ("127.0.0.1", 5)}
    assert client_ip(scope("203.0.113.9, 10.0.0.1")) == "203.0.113.9"
    assert client_ip(scope("6.6.6.6, 203.0.113.9, 10.0.0.1")) == "203.0.113.9"  # a forged entry is ignored
    assert client_ip(scope("203.0.113.9")) == "203.0.113.9"
    assert client_ip(scope(), 1) == "127.0.0.1"
    assert client_ip(scope("203.0.113.9, 10.0.0.1"), 0) == "10.0.0.1"
