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
