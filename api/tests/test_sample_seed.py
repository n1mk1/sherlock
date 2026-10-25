"""The cached sample (Implementation Plan D9.1): snapshot a built sample as a seed, then "Try with sample"
clones it for each user with fresh IDs: ready at once, independent of every other copy, and every part
works (rows, cards and evidence, the analysis, the canvas, a new edit, the notebook)."""

import json
import re

import pytest
from fastapi.testclient import TestClient

from sherlock.config import get_settings
from sherlock.db.connection import connect
from sherlock.sample_seed import ID, snapshot
from tests.test_jobs import db_rows

API = "/api/v1"


@pytest.fixture
def mocked(monkeypatch):
    from tests.test_stories import FIXTURE

    monkeypatch.setenv("LLM_MOCK", str(FIXTURE))
    get_settings.cache_clear()


@pytest.mark.usefixtures("run_jobs")
def test_try_with_sample_clones_the_seed_with_fresh_ids(mocked, client, app, monkeypatch, tmp_path):
    from tests.test_stories import _ready_with_stories

    ds = _ready_with_stories(client)
    cards = [c for c in client.get(f"{API}/datasets/{ds}/cards").json() if c["kind"] == "widget"][:2]
    canvas = client.get(f"{API}/datasets/{ds}/canvas").json()
    client.put(f"{API}/datasets/{ds}/canvas", json={"etag": canvas["etag"], "canvas": {"nodes": [
        {"id": "a", "type": "text", "x": 0, "y": 0, "width": 240, "height": 170, "sherlock": {"card_id": cards[0]["id"]}},
        {"id": "b", "type": "text", "x": 0, "y": 300, "width": 240, "height": 170, "sherlock": {"card_id": cards[1]["id"]}}],
        "edges": [{"id": "e", "fromNode": "a", "toNode": "b", "label": "compare"}]}})
    seed = tmp_path / "seed"
    db = connect(get_settings())
    try:
        meta = snapshot(get_settings(), db, ds, seed)
    finally:
        db.close()
    assert meta["counts"]["widgets"] >= 6 and meta["counts"]["runs"] >= 1 and (seed / "files" / "raw.csv").is_file()

    monkeypatch.setenv("SAMPLE_SEED_DIR", str(seed))
    get_settings.cache_clear()
    app.state.settings = get_settings()
    with TestClient(app) as alice, TestClient(app) as bob:
        a = alice.post(f"{API}/datasets/sample")
        assert a.status_code == 201, a.text
        a = a.json()
        assert a["status"] == "ready" and a["id"] != ds
        assert db_rows("SELECT is_sample FROM datasets WHERE id = ?", a["id"])[0]["is_sample"] == 1
        assert alice.post(f"{API}/datasets/sample").json()["id"] == a["id"]  # one sample per user
        b = bob.post(f"{API}/datasets/sample").json()
        assert b["id"] not in (a["id"], ds)

        # Every ID is new: nothing in the clone's rows names the seed's dataset, user or objects.
        seed_ids = set(ID.findall(json.dumps(json.loads((seed / "rows.json").read_text(encoding="utf-8"))["rows"])))
        seed_ids = {f"{p}_{u}" for p, u in seed_ids}
        clone_rows = json.dumps([dict(r) for r in db_rows("SELECT * FROM widgets WHERE dataset_id = ?", a["id"])] +
                                [dict(r) for r in db_rows("SELECT * FROM cards WHERE dataset_id = ?", a["id"])] +
                                [dict(r) for r in db_rows("SELECT * FROM canvases WHERE dataset_id = ?", a["id"])])
        assert not seed_ids & {m.group(0) for m in re.finditer(ID, clone_rows)}

        # It all works on the clone.
        widgets = alice.get(f"{API}/datasets/{a['id']}/widgets").json()["widgets"]
        assert len(widgets) == meta["counts"]["widgets"]
        for w in widgets:
            if w["spec"]["op"]["type"] == "sql":
                assert alice.get(f"{API}/widgets/{w['id']}/data").status_code == 200
        acards = alice.get(f"{API}/datasets/{a['id']}/cards").json()
        card = next(c for c in acards if c["kind"] == "widget" and c["facts"])
        chip = next(r for blk in card["body"]["blocks"] + card["headline"]["blocks"] for r in blk["runs"] if r["type"] == "chip")
        assert alice.get(f"{API}/cards/{card['id']}/evidence/{chip['id']}").json()["sql"]
        run = next(w for w in widgets if w["spec"]["op"]["type"] == "ml")["run_id"]
        mc = alice.get(f"{API}/runs/{run}/model-card")
        assert mc.status_code == 200, mc.text
        assert alice.get(f"{API}/runs/{run}/code").status_code == 200
        doc = alice.get(f"{API}/datasets/{a['id']}/canvas").json()["canvas"]
        assert {n["sherlock"]["card_id"] for n in doc["nodes"]} <= {c["id"] for c in acards} and doc["edges"][0]["label"] == "compare"
        rows = alice.get(f"{API}/datasets/{a['id']}/rows?limit=5").json()
        v = rows["version"]
        saved = alice.post(f"{API}/datasets/{a['id']}/edits", json={"base_version": v, "edits": [
            {"row_id": rows["rows"][0]["_row_id"], "column": "fare", "value": "1"}]})
        assert saved.status_code == 201, saved.text
        # Bob's copy is untouched by Alice's edit, and Alice can't see Bob's.
        assert bob.get(f"{API}/datasets/{b['id']}").json()["current_version"] == v
        assert alice.get(f"{API}/datasets/{b['id']}").status_code == 404
        from tests.test_notebook import _export

        out = _export(bob, b["id"], include_data=False)
        assert out["counts"]["widgets"] >= 5 and out["counts"]["runs"] >= 1


def test_the_shipped_seed_clones_and_works(client, app, monkeypatch):
    """The seed in `api/samples/seed/titanic3` (made by scripts/seed_sample.py with the real model) still
    loads into the current schema, and its dashboard, stories, analysis, canvas and rows all answer."""
    from sherlock.sample_seed import DEFAULT_SEED

    if not (DEFAULT_SEED / "rows.json").is_file():
        pytest.skip("no seed shipped yet")
    monkeypatch.setenv("SAMPLE_SEED_DIR", "")
    get_settings.cache_clear()
    app.state.settings = get_settings()
    r = client.post(f"{API}/datasets/sample")
    assert r.status_code == 201, r.text
    ds = r.json()
    assert ds["status"] == "ready" and ds["name"] == "titanic3.csv (sample)"
    widgets = client.get(f"{API}/datasets/{ds['id']}/widgets").json()["widgets"]
    cards = client.get(f"{API}/datasets/{ds['id']}/cards").json()
    assert len(widgets) >= 6 and {c["widget_id"] for c in cards if c["kind"] == "widget"} == {w["id"] for w in widgets}
    assert any(c["kind"] == "synthesis" for c in cards) and cards[0]["kind"] == "overview"
    for w in widgets:
        if w["spec"]["op"]["type"] == "sql":
            assert client.get(f"{API}/widgets/{w['id']}/data").status_code == 200, w["title"]
        else:
            assert client.get(f"{API}/runs/{w['run_id']}/model-card").status_code == 200
    canvas = client.get(f"{API}/datasets/{ds['id']}/canvas").json()["canvas"]
    assert len(canvas["nodes"]) >= 3 and canvas["edges"]
    assert client.get(f"{API}/datasets/{ds['id']}/rows?limit=3").json()["total"] == 1309
    assert client.get(f"{API}/datasets/{ds['id']}/report").status_code == 200

    # Every ID in the seed is new in the clone, in every table and JSON (canvas node and edge IDs too),
    # and the public seed doesn't name the machine that built it.
    from sherlock.sample_seed import TABLES

    seed = json.loads((DEFAULT_SEED / "rows.json").read_text(encoding="utf-8"))["rows"]
    seed_ids = {m.group(0) for m in ID.finditer(json.dumps(seed))}
    clone = json.dumps([dict(r) for t in TABLES for r in db_rows(
        f"SELECT * FROM {t} WHERE {'id' if t == 'datasets' else 'dataset_id'} = ?", ds["id"])])  # noqa: S608
    assert not seed_ids & {m.group(0) for m in ID.finditer(clone)}
    assert {n["id"] for n in canvas["nodes"]}.isdisjoint(seed_ids)
    assert all(j["owner_pid"] is None for j in seed["jobs"])
