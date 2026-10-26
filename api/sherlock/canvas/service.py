"""The Flow canvas (TRD §4.7, Schema §2.12): one JSON Canvas document per dataset.

Nodes are JSON Canvas nodes. A story card on the canvas is a `text` node with empty `text` and
`sherlock: {card_id}`; a note is a `text` node with its text. Edges carry `sherlock: {made_by, kind}`.
Writes are guarded by an etag (sha1 of the stored JSON): a `PUT` with a stale etag is `409`, so two
tabs can't overwrite each other. Card nodes of hard-deleted cards are pruned on read; nodes of
soft-deleted cards stay (the client hides them) so Undo restores them in place.
"""

import hashlib
import json
import math
import sqlite3

from sherlock.db.util import new_id, now_iso
from sherlock.errors import ApiError
from sherlock.jobs.events import emit

MAX_NODES = 400
MAX_EDGES = 800
MAX_TEXT = 4000
MAX_LABEL = 200
MAX_SIZE = 4000
NODE_TYPES = ("text", "file", "link", "group")
SIDES = ("top", "right", "bottom", "left")
EDGE_KINDS = ("summarized_in", "next", "contrasts", "custom")
NODE_KEYS = ("id", "type", "x", "y", "width", "height", "text", "color", "file", "url", "label", "sherlock")
EDGE_KEYS = ("id", "fromNode", "toNode", "fromSide", "toSide", "label", "color", "sherlock")
CARD_W, CARD_H = 240, 170


def empty() -> dict:
    return {"nodes": [], "edges": []}


def dump(doc: dict) -> str:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def etag_of(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _invalid(message: str) -> ApiError:
    return ApiError(422, "invalid", f"canvas: {message}")


def _number(value, what: str, lo: float, hi: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) or not lo <= value <= hi:
        raise _invalid(f"{what} must be a number between {lo:g} and {hi:g}")
    return round(float(value), 1)


def _text(value, what: str, limit: int) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise _invalid(f"{what} must be text of at most {limit} characters")
    return value


def validate(db: sqlite3.Connection, dataset_id: str, doc) -> dict:
    """The document as stored: known keys only, numbers checked, card nodes naming this dataset's cards,
    edges between existing nodes. A card node whose card is gone for good but was on the stored canvas (a
    tab saving what it read before the purge) is dropped with its edges rather than refused (plan 2b.6).
    Anything else is `422`."""
    if not isinstance(doc, dict) or not isinstance(doc.get("nodes", []), list) or not isinstance(doc.get("edges", []), list):
        raise _invalid("expected {nodes: [...], edges: [...]}")
    nodes, edges = doc.get("nodes", []), doc.get("edges", [])
    if len(nodes) > MAX_NODES or len(edges) > MAX_EDGES:
        raise _invalid(f"at most {MAX_NODES} nodes and {MAX_EDGES} edges")
    cards = {r["id"] for r in db.execute("SELECT id FROM cards WHERE dataset_id = ?", (dataset_id,))}
    # Cards that were on the stored canvas and are gone for good: their nodes are dropped, not refused.
    # A card node the stored canvas never had must still name one of this dataset's cards.
    row = db.execute("SELECT canvas_json FROM canvases WHERE dataset_id = ?", (dataset_id,)).fetchone()
    had = {(n.get("sherlock") or {}).get("card_id") for n in json.loads(row["canvas_json"])["nodes"]} if row else set()
    gone = {n["id"] for n in nodes if isinstance(n, dict) and isinstance(n.get("sherlock"), dict)
            and isinstance(n["sherlock"].get("card_id"), str) and n["sherlock"]["card_id"] in had - cards
            and isinstance(n.get("id"), str)}
    if gone:  # anything malformed is left for the checks below to refuse
        nodes = [n for n in nodes if not (isinstance(n, dict) and isinstance(n.get("id"), str) and n["id"] in gone)]
        edges = [e for e in edges if not (isinstance(e, dict) and any(isinstance(e.get(k), str) and e[k] in gone
                                                                      for k in ("fromNode", "toNode")))]
    out_nodes, ids, placed = [], set(), set()
    for n in nodes:
        if not isinstance(n, dict):
            raise _invalid("a node must be an object")
        nid = _text(n.get("id"), "node id", 64)
        if not nid or nid in ids:
            raise _invalid(f"node id {nid!r} is empty or repeated")
        ids.add(nid)
        if n.get("type") not in NODE_TYPES:
            raise _invalid(f"node {nid}: type must be one of {', '.join(NODE_TYPES)}")
        node = {"id": nid, "type": n["type"], "x": _number(n.get("x"), "x", -1e6, 1e6), "y": _number(n.get("y"), "y", -1e6, 1e6),
                "width": _number(n.get("width"), "width", 1, MAX_SIZE), "height": _number(n.get("height"), "height", 1, MAX_SIZE)}
        for key in ("text", "file", "url", "label"):
            if n.get(key) is not None:
                node[key] = _text(n[key], f"node {nid} {key}", MAX_TEXT)
        if n.get("color") is not None:
            node["color"] = _text(n["color"], f"node {nid} color", 16)
        meta = n.get("sherlock")
        if meta is not None:
            if not isinstance(meta, dict):
                raise _invalid(f"node {nid}: sherlock must be an object")
            card_id = meta.get("card_id")
            if card_id is not None:
                if not isinstance(card_id, str) or card_id not in cards:
                    raise _invalid(f"node {nid}: card {card_id!r} isn't one of this dataset's cards")
                if card_id in placed:
                    raise _invalid(f"card {card_id} is on the canvas twice")
                placed.add(card_id)
                node["text"] = ""
                node["sherlock"] = {"card_id": card_id}
        out_nodes.append(node)
    out_edges, edge_ids = [], set()
    for e in edges:
        if not isinstance(e, dict):
            raise _invalid("an edge must be an object")
        eid = _text(e.get("id"), "edge id", 64)
        if not eid or eid in edge_ids:
            raise _invalid(f"edge id {eid!r} is empty or repeated")
        edge_ids.add(eid)
        a, b = e.get("fromNode"), e.get("toNode")
        if not isinstance(a, str) or not isinstance(b, str) or a not in ids or b not in ids or a == b:
            raise _invalid(f"edge {eid} must join two different nodes on the canvas")
        edge = {"id": eid, "fromNode": a, "toNode": b}
        for key in ("fromSide", "toSide"):
            if e.get(key) is not None:
                if e[key] not in SIDES:
                    raise _invalid(f"edge {eid}: {key} must be one of {', '.join(SIDES)}")
                edge[key] = e[key]
        if e.get("label"):
            edge["label"] = _text(e["label"], f"edge {eid} label", MAX_LABEL)
        if e.get("color") is not None:
            edge["color"] = _text(e["color"], f"edge {eid} color", 16)
        meta = e.get("sherlock") or {}
        if not isinstance(meta, dict):
            raise _invalid(f"edge {eid}: sherlock must be an object")
        made_by = meta.get("made_by", "user")
        kind = meta.get("kind", "custom")
        if made_by not in ("user", "ai") or kind not in EDGE_KINDS:
            raise _invalid(f"edge {eid}: sherlock.made_by is user or ai, and kind one of {', '.join(EDGE_KINDS)}")
        edge["sherlock"] = {"made_by": made_by, "kind": kind}
        out_edges.append(edge)
    return {"nodes": out_nodes, "edges": out_edges}


def _store(db: sqlite3.Connection, dataset_id: str, doc: dict) -> str:
    text = dump(doc)
    etag = etag_of(text)
    db.execute("INSERT INTO canvases (dataset_id, canvas_json, etag, updated_at) VALUES (?, ?, ?, ?) "
               "ON CONFLICT(dataset_id) DO UPDATE SET canvas_json = excluded.canvas_json, etag = excluded.etag, "
               "updated_at = excluded.updated_at", (dataset_id, text, etag, now_iso()))
    return etag


def read(db: sqlite3.Connection, dataset_id: str) -> tuple[dict, str]:
    """The canvas and its etag. Card nodes whose card is gone for good are pruned (with their edges),
    which writes the canvas back and changes the etag."""
    row = db.execute("SELECT canvas_json, etag FROM canvases WHERE dataset_id = ?", (dataset_id,)).fetchone()
    if row is None:
        doc = empty()
        return doc, etag_of(dump(doc))
    doc = json.loads(row["canvas_json"])
    cards = {r["id"] for r in db.execute("SELECT id FROM cards WHERE dataset_id = ?", (dataset_id,))}
    gone = {n["id"] for n in doc["nodes"] if (n.get("sherlock") or {}).get("card_id") and n["sherlock"]["card_id"] not in cards}
    if not gone:
        return doc, row["etag"]
    doc = {"nodes": [n for n in doc["nodes"] if n["id"] not in gone],
           "edges": [e for e in doc["edges"] if e["fromNode"] not in gone and e["toNode"] not in gone]}
    return doc, _store(db, dataset_id, doc)


def _saved(db, bus, dataset: sqlite3.Row, etag: str) -> None:
    db.execute("UPDATE datasets SET state_rev = state_rev + 1 WHERE id = ?", (dataset["id"],))
    emit(db, bus, dataset["id"], dataset["user_id"], "canvas.updated", {"etag": etag})


def write(db: sqlite3.Connection, bus, dataset: sqlite3.Row, doc, etag: str) -> str:
    """`PUT /canvas`: store the document when `etag` is the stored one, else `409` with the current etag."""
    clean = validate(db, dataset["id"], doc)
    db.execute("BEGIN IMMEDIATE")
    try:
        _, current = read(db, dataset["id"])
        if etag != current:
            raise ApiError(409, "conflict", "The canvas changed in another tab. Reload it to see the latest.",
                           extra={"etag": current})
        new = _store(db, dataset["id"], clean)
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    if new != current:
        _saved(db, bus, dataset, new)
    return new


def mutate(db: sqlite3.Connection, bus, dataset: sqlite3.Row, change) -> tuple[dict, str]:
    """Read, apply `change(doc)` in place, validate and store, in one transaction: what the AI
    actions (`add_canvas_node`, `add_canvas_edge`) use, so they never race a tab's save."""
    db.execute("BEGIN IMMEDIATE")
    try:
        doc, _ = read(db, dataset["id"])
        change(doc)
        doc = validate(db, dataset["id"], doc)
        etag = _store(db, dataset["id"], doc)
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise
    _saved(db, bus, dataset, etag)
    return doc, etag


# --- the AI actions (TRD §8.2: add_canvas_node, add_canvas_edge) ------------------------------------

def card_node(doc: dict, card_id: str) -> dict | None:
    return next((n for n in doc["nodes"] if (n.get("sherlock") or {}).get("card_id") == card_id), None)


def add_card_node(doc: dict, card_id: str, x: float, y: float) -> dict:
    """Place a card (or return its node when it is already on the canvas)."""
    node = card_node(doc, card_id)
    if node is None:
        node = {"id": new_id("nd"), "type": "text", "x": round(x), "y": round(y), "width": CARD_W, "height": CARD_H,
                "text": "", "sherlock": {"card_id": card_id}}
        doc["nodes"].append(node)
    return node


def add_edge(doc: dict, a: str, b: str, label: str | None, kind: str = "custom", made_by: str = "ai") -> dict:
    edge = {"id": new_id("ed"), "fromNode": a, "toNode": b, "sherlock": {"made_by": made_by, "kind": kind}}
    if label:
        edge["label"] = label
    doc["edges"].append(edge)
    return edge


def beside(nodes: list[dict], doc: dict) -> tuple[float, float]:
    """Where a new node for these nodes goes: right of them, level with their centroid (so it doesn't
    cover them), or right of everything when none of them is placed."""
    if not nodes:
        right = max((n["x"] + n["width"] for n in doc["nodes"]), default=0)
        return right + 120, 0
    cy = sum(n["y"] + n["height"] / 2 for n in nodes) / len(nodes)
    right = max(n["x"] + n["width"] for n in nodes)
    return right + 160, cy - CARD_H / 2
