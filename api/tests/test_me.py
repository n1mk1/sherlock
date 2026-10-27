from sherlock.config import get_settings
from sherlock.db.connection import connect

DEFAULTS = {
    "theme": "system",
    "accent": "verdigris",
    "chatbar": "pinned",
    "after_upload": "ask",
    "cleaning_mode": "auto",
    "reduce_motion": "system",
}


def test_get_me_returns_prd_default_settings(client):
    body = client.get("/api/v1/me").json()
    assert body["user_id"].startswith("usr_")
    assert body["created_at"].endswith("Z")
    assert body["settings"] == DEFAULTS


def test_put_settings_merges_and_persists(client):
    res = client.put("/api/v1/me/settings", json={"theme": "dark", "accent": "ember"})
    assert res.status_code == 200
    assert res.json() == DEFAULTS | {"theme": "dark", "accent": "ember"}

    res = client.put("/api/v1/me/settings", json={"chatbar": "hidden"})
    assert res.json() == DEFAULTS | {"theme": "dark", "accent": "ember", "chatbar": "hidden"}
    assert client.get("/api/v1/me").json()["settings"]["accent"] == "ember"


def test_put_settings_rejects_bad_values_with_the_error_envelope(client):
    # The removed dashboard settings are unknown keys now.
    for body in ({"accent": "neon"}, {"font_size": 14}, {"story_updates": "ask"}, {"default_tab": "csv"}):
        res = client.put("/api/v1/me/settings", json=body)
        assert res.status_code == 422
        error = res.json()["error"]
        assert error["code"] == "invalid"
        assert error["request_id"] == res.headers["x-request-id"]
    assert client.get("/api/v1/me").json()["settings"] == DEFAULTS


def test_stale_stored_values_fall_back_to_defaults(client):
    user_id = client.get("/api/v1/me").json()["user_id"]
    conn = connect(get_settings())
    conn.execute(
        "UPDATE users SET settings_json = ? WHERE id = ?",
        ('{"accent": "retired-accent", "theme": "light", "story_updates": "ask", "default_tab": "flow"}', user_id),
    )
    conn.close()
    settings = client.get("/api/v1/me").json()["settings"]
    assert settings["accent"] == "verdigris"
    assert settings["theme"] == "light"
    assert settings == DEFAULTS | {"theme": "light"}  # a removed setting someone stored is ignored


def test_unknown_route_uses_the_error_envelope(client):
    res = client.get("/api/v1/nope")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "not_found"
