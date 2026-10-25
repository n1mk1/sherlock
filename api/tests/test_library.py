"""Library management (TRD §4.2, PRD LOAD-5): rename, last tab, soft delete with restore, raw download."""

from sherlock.db.connection import connect
from sherlock.config import get_settings

API = "/api/v1"
CSV = b"name,age\nAnn,30\nBob,41\n"


def upload(client):
    r = client.post(f"{API}/datasets", files={"file": ("people.csv", CSV, "text/csv")})
    assert r.status_code == 201, r.text
    return r.json()


def test_rename_and_last_tab(client):
    ds = upload(client)
    r = client.patch(f"{API}/datasets/{ds['id']}", json={"name": "  People  ", "last_tab": "csv"})
    assert r.status_code == 200 and r.json()["name"] == "People" and r.json()["last_tab"] == "csv"
    assert client.patch(f"{API}/datasets/{ds['id']}", json={"name": ""}).status_code == 422
    assert client.patch(f"{API}/datasets/{ds['id']}", json={"last_tab": "nope"}).status_code == 422
    assert client.patch(f"{API}/datasets/{ds['id']}", json={"owner": "x"}).status_code == 422


def test_delete_hides_and_restore_brings_back(client):
    ds = upload(client)
    assert client.delete(f"{API}/datasets/{ds['id']}").status_code == 204
    assert client.get(f"{API}/datasets/{ds['id']}").status_code == 404
    assert [d["id"] for d in client.get(f"{API}/datasets").json()] == []
    # The queued profile job was cancelled with it, and comes back on restore.
    r = client.post(f"{API}/datasets/{ds['id']}/restore")
    assert r.status_code == 200 and r.json()["id"] == ds["id"]
    assert [d["id"] for d in client.get(f"{API}/datasets").json()] == [ds["id"]]
    kinds = [(j["kind"], j["status"]) for j in client.get(f"{API}/jobs", params={"dataset_id": ds["id"]}).json()]
    assert kinds == [("profile", "queued"), ("profile", "cancelled")]


def test_restore_window_is_ten_minutes(client):
    ds = upload(client)
    client.delete(f"{API}/datasets/{ds['id']}")
    db = connect(get_settings())
    db.execute("UPDATE datasets SET deleted_at = '2000-01-01T00:00:00.000Z' WHERE id = ?", (ds["id"],))
    db.close()
    assert client.post(f"{API}/datasets/{ds['id']}/restore").status_code == 404


def test_raw_csv_is_the_upload(client):
    ds = upload(client)
    r = client.get(f"{API}/datasets/{ds['id']}/raw.csv")
    assert r.status_code == 200 and r.content == CSV
    assert 'filename="people-raw.csv"' in r.headers["content-disposition"]
