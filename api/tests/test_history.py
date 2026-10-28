"""The toolbar's Undo and Redo (docs/plans/chat-commands.md §4): back up to `undo_depth` states in a row, forward
again through what was undone, reusing each version's file; any new step clears Redo."""

import pytest

from tests.test_jobs import db_rows, wait_status

API = "/api/v1"
pytestmark = pytest.mark.usefixtures("run_jobs")


@pytest.fixture
def ready(client):
    ds = client.post(f"{API}/datasets/sample").json()
    wait_status(client, ds["id"], "offer")
    client.post(f"{API}/datasets/{ds['id']}/use-as-is")
    wait_status(client, ds["id"], "ready")
    return client.get(f"{API}/datasets/{ds['id']}").json()


def fare(client, ds, row_id=1):
    rows = client.get(f"{API}/datasets/{ds}/rows", params={"offset": row_id - 1, "limit": 1}).json()["rows"]
    return rows[0]["cells"]["fare"]


def edit(client, ds, value):
    v = client.get(f"{API}/datasets/{ds}").json()["current_version"]
    got = client.post(f"{API}/datasets/{ds}/edits", json={"base_version": v, "edits": [{"row_id": 1, "column": "fare", "value": value}]})
    assert got.status_code == 201, got.text
    return got.json()["version"]


def move(client, ds, way):
    v = client.get(f"{API}/datasets/{ds}").json()["current_version"]
    return client.post(f"{API}/datasets/{ds}/{way}", json={"base_version": v})


def parquet(ds, version):
    return db_rows("SELECT parquet_path FROM versions WHERE dataset_id = ? AND version = ?", ds, version)[0][0]


def test_undo_goes_back_three_states_and_redo_comes_forward_on_the_same_files(client, ready):
    ds = ready["id"]
    start = fare(client, ds)
    versions = [edit(client, ds, str(x)) for x in (1, 2, 3, 4)]
    h = client.get(f"{API}/datasets/{ds}/history").json()
    assert h["undo"] is not None and h["redo"] is None and h["depth_left"] == 3

    for expected in (3, 2, 1):
        got = move(client, ds, "undo")
        assert got.status_code == 200, got.text
        assert fare(client, ds) == expected
    h = client.get(f"{API}/datasets/{ds}/history").json()
    assert h["undo"] is None and h["depth_left"] == 0 and h["redo"] is not None
    refused = move(client, ds, "undo")
    assert refused.status_code == 409 and "up to 3" in refused.json()["error"]["message"]
    assert fare(client, ds) == 1 and fare(client, ds) != start

    # Redo comes back through the same states, each on the file it had before (no data rewritten).
    for expected, was in ((2, versions[1]), (3, versions[2]), (4, versions[3])):
        got = move(client, ds, "redo").json()
        assert fare(client, ds) == expected
        assert parquet(ds, got["version"]) == parquet(ds, was)
        assert got["step"]["kind"] == "redo"
    assert move(client, ds, "redo").status_code == 409
    assert client.get(f"{API}/datasets/{ds}/history").json()["depth_left"] == 3


def test_a_new_change_after_an_undo_clears_redo(client, ready):
    ds = ready["id"]
    edit(client, ds, "1")
    edit(client, ds, "2")
    assert move(client, ds, "undo").status_code == 200
    assert client.get(f"{API}/datasets/{ds}/history").json()["redo"] is not None
    edit(client, ds, "9")
    h = client.get(f"{API}/datasets/{ds}/history").json()
    assert h["redo"] is None and h["depth_left"] == 3 and fare(client, ds) == 9
    assert move(client, ds, "redo").status_code == 409


def test_undo_never_takes_back_the_typing_step(client, ready):
    ds = ready["id"]
    h = client.get(f"{API}/datasets/{ds}/history").json()
    assert h["undo"] is None and h["redo"] is None  # only the automatic typing step so far
    assert move(client, ds, "undo").status_code == 409


def test_a_redone_edit_protects_its_cells_again(client, ready):
    ds = ready["id"]
    edit(client, ds, "7")
    move(client, ds, "undo")
    assert not db_rows("SELECT 1 FROM user_edited_cells WHERE dataset_id = ?", ds)
    move(client, ds, "redo")
    assert [tuple(r) for r in db_rows("SELECT row_id, column FROM user_edited_cells WHERE dataset_id = ?", ds)] == [(1, "fare")]
