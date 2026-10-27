import sqlite3

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient

from sherlock.config import get_settings
from sherlock.db.connection import connect
from sherlock.db.util import now_iso
from sherlock.ownership import BARE_ID_KINDS, Owned, owned, owned_dataset


def seed_dataset(user_id: str, dataset_id: str, deleted: bool = False) -> None:
    conn = connect(get_settings())
    now = now_iso()
    conn.execute(
        "INSERT INTO datasets (id, user_id, name, original_filename, status, import_options_json, "
        "expires_at, created_at, deleted_at) VALUES (?, ?, 'd', 'd.csv', 'ready', '{}', ?, ?, ?)",
        (dataset_id, user_id, now, now, now if deleted else None),
    )
    conn.execute(
        "INSERT INTO runs (id, dataset_id, version, recipe, method, scope_json, params_json, cache_key, status, "
        "created_by, created_at) VALUES (?, ?, 1, 'driver_analysis', 'auto', '{}', '{}', 'k', 'done', 'user', ?)",
        (f"run_{dataset_id}", dataset_id, now),
    )
    conn.execute(
        "INSERT INTO jobs (id, dataset_id, user_id, kind, status, created_at) "
        "VALUES (?, ?, ?, 'profile', 'done', ?)",
        (f"job_{dataset_id}", dataset_id, user_id, now),
    )
    conn.close()


@pytest.fixture
def owned_app(app):
    router = APIRouter(prefix="/api/v1")

    @router.get("/datasets/{dataset_id}/probe")
    def dataset_probe(row: sqlite3.Row = Depends(owned_dataset)):
        return {"id": row["id"]}

    @router.get("/runs/{rid}/probe")
    def run_probe(o: Owned = Depends(owned("run"))):
        return {"id": o.id, "dataset_id": o.dataset_id}

    @router.get("/jobs/{jid}/probe")
    def job_probe(o: Owned = Depends(owned("job"))):
        return {"id": o.id, "dataset_id": o.dataset_id}

    app.include_router(router)
    return app


def test_owner_sees_their_objects_and_others_get_404(owned_app):
    with TestClient(owned_app) as alice, TestClient(owned_app) as bob:
        alice_id = alice.get("/api/v1/me").json()["user_id"]
        bob.get("/api/v1/me")
        seed_dataset(alice_id, "ds_alice")

        assert alice.get("/api/v1/datasets/ds_alice/probe").json() == {"id": "ds_alice"}
        assert alice.get("/api/v1/runs/run_ds_alice/probe").json() == {
            "id": "run_ds_alice", "dataset_id": "ds_alice",
        }
        assert alice.get("/api/v1/jobs/job_ds_alice/probe").status_code == 200

        for path in (
            "/api/v1/datasets/ds_alice/probe",
            "/api/v1/runs/run_ds_alice/probe",
            "/api/v1/jobs/job_ds_alice/probe",
            "/api/v1/datasets/ds_missing/probe",
        ):
            res = bob.get(path)
            assert res.status_code == 404, path
            assert res.json()["error"]["code"] == "not_found"


def test_deleted_dataset_hides_its_children(owned_app):
    with TestClient(owned_app) as alice:
        alice_id = alice.get("/api/v1/me").json()["user_id"]
        seed_dataset(alice_id, "ds_gone", deleted=True)
        assert alice.get("/api/v1/datasets/ds_gone/probe").status_code == 404
        assert alice.get("/api/v1/runs/run_ds_gone/probe").status_code == 404
        assert alice.get("/api/v1/jobs/job_ds_gone/probe").status_code == 404


def test_the_removed_surfaces_have_no_bare_id_kind():
    assert not {"widget", "card", "fact_sheet"} & set(BARE_ID_KINDS)


def test_every_bare_id_kind_maps_to_a_real_table():
    conn = connect(get_settings())
    from sherlock.db.migrate import migrate

    migrate(conn)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for kind, (table, _) in BARE_ID_KINDS.items():
        assert table in tables, kind
        columns = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        assert {"id", "dataset_id"} <= columns, kind
    conn.close()
