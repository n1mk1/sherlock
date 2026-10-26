"""The Flow canvas (TRD §4.7, §7.4.1; PRD FLOW-1–FLOW-6): JSON Canvas with an etag, validation,
pruning, "make sense of this" as a synthesis card with chips through its sources, `ask_story`, and
Add to Flow."""

import json
import shutil
from pathlib import Path

import pytest

from sherlock.config import get_settings
from tests.test_jobs import db_rows, upload

API = "/api/v1"
LLM = Path(__file__).parent / "fixtures" / "llm"


def _canvas(client, ds):
    r = client.get(f"{API}/datasets/{ds}/canvas")
    assert r.status_code == 200, r.text
    return r.json()


def test_put_needs_the_current_etag_and_a_valid_document(client):
    ds = upload(client, b"a,b\n1,2\n3,4\n")["id"]
    got = _canvas(client, ds)
    assert got["canvas"] == {"nodes": [], "edges": []} and got["etag"]
    note = {"id": "n1", "type": "text", "x": 10, "y": 20, "width": 220, "height": 80, "text": "Check the gap", "junk": 1}
    other = {**note, "id": "n2", "x": 400}
    doc = {"nodes": [note, other], "edges": [{"id": "e1", "fromNode": "n1", "toNode": "n2", "label": "why?"}]}
    r = client.put(f"{API}/datasets/{ds}/canvas", json={"canvas": doc, "etag": got["etag"]})
    assert r.status_code == 200, r.text
    etag = r.json()["etag"]
    saved = _canvas(client, ds)
    assert saved["etag"] == etag and "junk" not in saved["canvas"]["nodes"][0]
    assert saved["canvas"]["edges"][0]["sherlock"] == {"made_by": "user", "kind": "custom"}
    # A second tab still holding the first etag can't overwrite it.
    stale = client.put(f"{API}/datasets/{ds}/canvas", json={"canvas": {"nodes": [], "edges": []}, "etag": got["etag"]})
    assert stale.status_code == 409 and stale.json()["error"]["etag"] == etag
    events = [r["type"] for r in db_rows("SELECT type FROM job_events WHERE dataset_id = ?", ds)]
    assert events.count("canvas.updated") == 1
    for bad in (
        {"nodes": [note], "edges": [{"id": "e1", "fromNode": "n1", "toNode": "ghost"}]},
        {"nodes": [note, {**note}], "edges": []},
        {"nodes": [{**note, "x": "far"}], "edges": []},
        {"nodes": [{**note, "sherlock": {"card_id": "crd_not_mine"}}], "edges": []},
        {"nodes": [{**note, "type": "shape"}], "edges": []},
        # Wrong shapes inside a valid-looking document were 500s (Day 8 review).
        {"nodes": [note, other], "edges": [{"id": "e1", "fromNode": ["n1"], "toNode": "n2"}]},
        {"nodes": [note, other], "edges": [{"id": "e1", "fromNode": "n1", "toNode": "n2", "sherlock": "ai"}]},
        {"nodes": [{**note, "sherlock": {"card_id": ["crd_x"]}}], "edges": []},
    ):
        r = client.put(f"{API}/datasets/{ds}/canvas", json={"canvas": bad, "etag": etag})
        assert r.status_code == 422, (bad, r.text)


def test_another_users_canvas_is_404(app, client):
    from fastapi.testclient import TestClient

    ds = upload(client, b"a,b\n1,2\n")["id"]
    with TestClient(app) as other:
        assert other.get(f"{API}/datasets/{ds}/canvas").status_code == 404
        assert other.put(f"{API}/datasets/{ds}/canvas", json={"canvas": {"nodes": [], "edges": []}, "etag": "x"}).status_code == 404


@pytest.fixture
def flow_mock(monkeypatch, tmp_path):
    folder = tmp_path / "llm"
    folder.mkdir()
    for name in ("stories_titanic.json", "flow_titanic.json", "chat_titanic.json"):
        shutil.copy(LLM / name, folder / name)
    monkeypatch.setenv("LLM_MOCK", str(folder))
    get_settings.cache_clear()


def _ready(client):
    from tests.test_stories import _ready_with_stories

    return _ready_with_stories(client)


def _chat(client, ds, text, **context):
    r = client.post(f"{API}/datasets/{ds}/chat", json={"text": text, "context": {"tab": "flow", **context}})
    assert r.status_code == 200, r.text
    frames = [f for f in r.text.split("\n\n") if f.startswith("event: message")]
    return json.loads(frames[-1].split("data: ", 1)[1])


@pytest.mark.usefixtures("run_jobs")
def test_make_sense_adds_a_synthesis_card_connected_to_its_sources(flow_mock, client):
    ds = _ready(client)
    cards = [c for c in client.get(f"{API}/datasets/{ds}/cards").json() if c["kind"] == "widget" and "n" in c["facts"]][:2]
    assert len(cards) == 2
    got = _canvas(client, ds)
    doc = {"nodes": [{"id": f"n{i}", "type": "text", "x": 0, "y": 200 * i, "width": 240, "height": 170, "text": "",
                      "sherlock": {"card_id": c["id"]}} for i, c in enumerate(cards)], "edges": []}
    client.put(f"{API}/datasets/{ds}/canvas", json={"canvas": doc, "etag": got["etag"]})

    one = _chat(client, ds, "Make sense of this", selected_card_ids=[cards[0]["id"]])
    assert "at least two cards" in one["text"]

    msg = _chat(client, ds, "Make sense of this", selected_card_ids=[c["id"] for c in cards])
    synth = next(c for c in client.get(f"{API}/datasets/{ds}/cards").json() if c["kind"] == "synthesis")
    assert synth["source_card_ids"] == [c["id"] for c in cards] and synth["narrated_by"]
    chips = [r for b in synth["body"]["blocks"] for r in b["runs"] if r["type"] == "chip"]
    assert {r["key"] for r in chips} == {f"{cards[0]['id']}.n", f"{cards[1]['id']}.n"}
    for r in chips:  # each number is its source card's fact
        source = next(c for c in cards if r["key"].startswith(c["id"]))
        assert r["value"] == source["facts"]["n"]["formatted"] == synth["facts"][r["key"]]["formatted"]
        ev = client.get(f"{API}/cards/{synth['id']}/evidence/{r['id']}").json()
        assert ev["sql"] and ev["key"] == r["key"] and ev["card_id"] == source["id"]
    assert {s["card_id"] for s in msg["sources"] if s["kind"] == "card"} == {c["id"] for c in cards}

    after = _canvas(client, ds)["canvas"]
    node = next(n for n in after["nodes"] if n.get("sherlock", {}).get("card_id") == synth["id"])
    assert node["x"] > 240  # right of its sources, not on top of them
    edges = [e for e in after["edges"] if e["toNode"] == node["id"]]
    assert {e["fromNode"] for e in edges} == {"n0", "n1"}
    assert all(e["label"] == "summarized in" and e["sherlock"] == {"made_by": "ai", "kind": "summarized_in"} for e in edges)

    # The notebook: the synthesis after the dashboard, and the canvas's notes when asked for (PRD NB-6).
    import nbformat

    from tests.test_notebook import _export

    etag = _canvas(client, ds)["etag"]
    after["nodes"].append({"id": "note1", "type": "text", "x": 900, "y": 0, "width": 220, "height": 80,
                           "text": "Check the gap before the pitch."})
    assert client.put(f"{API}/datasets/{ds}/canvas", json={"canvas": after, "etag": etag}).status_code == 200
    out = _export(client, ds, include_notes=True, include_data=False)
    assert out["counts"]["notes"] == 1
    nb = nbformat.reads(client.get(out["download_url"]).text, as_version=4)
    md = [c.source for c in nb.cells if c.cell_type == "markdown"]
    flow_at = next(i for i, m in enumerate(md) if m.startswith("## From the Flow canvas"))
    synth_md = next(m for m in md[flow_at:] if m.startswith("### Both cards"))
    assert all(r["value"] in synth_md for r in chips) and "<details><summary>Evidence</summary>" in synth_md
    assert any("> Check the gap before the pitch." in m for m in md[flow_at:])
    without = _export(client, ds, include_data=False)
    assert without["counts"]["notes"] == 0

    # The cascade: a number the synthesis cites moved, so it says its sources changed.
    db_rows("UPDATE fact_sheets SET facts_json = replace(facts_json, ?, ?) WHERE id = ?",
            f'"formatted": "{cards[0]["facts"]["n"]["formatted"]}"', '"formatted": "-1"', cards[0]["fact_sheet_id"])
    from sherlock.db.connection import connect
    from sherlock.stories import synthesis

    conn = connect(get_settings())
    try:
        dataset = conn.execute("SELECT * FROM datasets WHERE id = ?", (ds,)).fetchone()
        assert synthesis.check_sources(conn, None, dataset) == 1
    finally:
        conn.close()
    assert client.get(f"{API}/cards/{synth['id']}").json()["status"] == "sources_changed"


@pytest.mark.usefixtures("run_jobs")
def test_ask_story_answers_from_the_cards_and_adds_to_flow(flow_mock, client):
    ds = _ready(client)
    card = next(c for c in client.get(f"{API}/datasets/{ds}/cards").json() if c["kind"] == "widget" and "n" in c["facts"])
    msg = _chat(client, ds, "What does this card say about the passengers?", selected_card_ids=[card["id"]])
    text = next(b for b in msg["blocks"] if b["type"] == "text")
    chip = next(r for b in text["body"]["blocks"] for r in b["runs"] if r["type"] == "chip")
    assert chip["key"] == f"{card['id']}.n" and chip["value"] == card["facts"]["n"]["formatted"]
    action = next(a for a in msg["actions"] if a["kind"] == "add_to_flow")
    added = client.post(f"{API}/messages/{msg['id']}/pin", json={"target": "flow", "block_index": action["block_index"]})
    assert added.status_code == 201, added.text
    answer = added.json()
    assert answer["kind"] == "answer" and answer["fact_sheet_id"] and answer["facts"][chip["key"]]["formatted"] == chip["value"]
    ev = client.get(f"{API}/cards/{answer['id']}/evidence/{chip['id']}").json()
    assert ev["sql"]
    nodes = _canvas(client, ds)["canvas"]["nodes"]
    assert any(n.get("sherlock", {}).get("card_id") == answer["id"] for n in nodes)


def test_pruning_drops_nodes_of_cards_that_are_gone(client):
    from sherlock.db.util import now_iso

    ds = upload(client, b"a,b\n1,2\n")["id"]
    now = now_iso()
    db_rows("INSERT INTO cards (id, dataset_id, kind, headline_json, body_json, status, version, created_at, updated_at) "
            "VALUES ('crd_x', ?, 'synthesis', '{\"blocks\": []}', '{\"blocks\": []}', 'ready', 1, ?, ?)", ds, now, now)
    got = _canvas(client, ds)
    doc = {"nodes": [{"id": "c", "type": "text", "x": 0, "y": 0, "width": 240, "height": 170, "sherlock": {"card_id": "crd_x"}},
                     {"id": "n", "type": "text", "x": 300, "y": 0, "width": 220, "height": 80, "text": "note"}],
           "edges": [{"id": "e", "fromNode": "c", "toNode": "n"}]}
    etag = client.put(f"{API}/datasets/{ds}/canvas", json={"canvas": doc, "etag": got["etag"]}).json()["etag"]
    db_rows("UPDATE cards SET deleted_at = ? WHERE id = 'crd_x'", now)  # soft-deleted: the node stays for Undo
    assert len(_canvas(client, ds)["canvas"]["nodes"]) == 2
    db_rows("DELETE FROM cards WHERE id = 'crd_x'")  # purged: the node and its edge go
    after = _canvas(client, ds)
    assert [n["id"] for n in after["canvas"]["nodes"]] == ["n"] and after["canvas"]["edges"] == [] and after["etag"] != etag


def test_purge_prunes_the_canvas_and_a_save_drops_a_card_that_is_gone(client):
    """Plan 2b.6 (A34): purge prunes the nodes of the cards it hard-deletes and emits `canvas.updated`, so
    an open canvas reloads; a tab that saves a canvas it read before a card was hard-deleted loses that
    node instead of getting a 422. A card the canvas never had must still be this dataset's."""
    from sherlock.db.connection import connect
    from sherlock.db.util import now_iso
    from sherlock.jobs.purge import purge

    ds = upload(client, b"a,b\n1,2\n")["id"]
    now = now_iso()
    for cid in ("crd_keep", "crd_gone", "crd_purged"):
        db_rows("INSERT INTO cards (id, dataset_id, kind, headline_json, body_json, status, version, created_at, updated_at) "
                "VALUES (?, ?, 'synthesis', '{\"blocks\": []}', '{\"blocks\": []}', 'ready', 1, ?, ?)", cid, ds, now, now)

    def node(nid, cid, x):
        return {"id": nid, "type": "text", "x": x, "y": 0, "width": 240, "height": 170, "sherlock": {"card_id": cid}}

    doc = {"nodes": [node("k", "crd_keep", 0), node("g", "crd_gone", 300), node("p", "crd_purged", 600)],
           "edges": [{"id": "e", "fromNode": "k", "toNode": "g"}]}
    etag = client.put(f"{API}/datasets/{ds}/canvas", json={"canvas": doc, "etag": _canvas(client, ds)["etag"]}).json()["etag"]

    db_rows("DELETE FROM cards WHERE id = 'crd_gone'")  # gone for good, before any read pruned the canvas
    # The save reads (and prunes) the stored canvas, so the tab is told to reload, not that its card is bad.
    stale = client.put(f"{API}/datasets/{ds}/canvas", json={"canvas": doc, "etag": etag})
    assert stale.status_code == 409, stale.text
    saved = client.put(f"{API}/datasets/{ds}/canvas", json={"canvas": doc, "etag": stale.json()["error"]["etag"]})
    assert saved.status_code == 200, saved.text  # the reloaded tab's save: the gone card's node is dropped
    after = _canvas(client, ds)["canvas"]
    assert [n["id"] for n in after["nodes"]] == ["k", "p"] and after["edges"] == []

    db_rows("UPDATE cards SET deleted_at = '2000-01-01T00:00:00.000Z' WHERE id = 'crd_purged'")
    before = len([r for r in db_rows("SELECT type FROM job_events WHERE dataset_id = ?", ds) if r["type"] == "canvas.updated"])
    db = connect(client.app.state.settings)
    try:
        purge(client.app.state.settings, db, None)
    finally:
        db.close()
    events = [r["type"] for r in db_rows("SELECT type FROM job_events WHERE dataset_id = ?", ds)]
    assert events.count("canvas.updated") == before + 1
    stored = db_rows("SELECT canvas_json FROM canvases WHERE dataset_id = ?", ds)[0]["canvas_json"]
    assert "crd_purged" not in stored and "crd_keep" in stored
