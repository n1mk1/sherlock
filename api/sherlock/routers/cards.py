"""Story cards (TRD §4.6): list, read, edit, refresh, suggestions, badges, delete and restore, the
fact sheets behind them, evidence per chip, and the relation graph."""

import json
import sqlite3

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict

from sherlock.db.connection import get_db
from sherlock.db.util import now_iso
from sherlock.errors import ApiError, not_found
from sherlock.jobs.stories import queue_stories
from sherlock.ownership import Owned, owned, owned_dataset
from sherlock.stories import service as stories
from sherlock.stories import synthesis

router = APIRouter(tags=["cards"])


class CardEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    headline: dict | None = None
    body: dict | None = None


def _card(db, card_id: str) -> sqlite3.Row:
    return stories.card_row(db, card_id)


def _dataset(db, dataset_id: str) -> sqlite3.Row:
    return db.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()


def _changed(request: Request, db, card_id: str) -> dict:
    r = _card(db, card_id)
    db.execute("UPDATE datasets SET state_rev = state_rev + 1 WHERE id = ?", (r["dataset_id"],))
    return stories.emit_card(db, request.app.state.bus, _dataset(db, r["dataset_id"]), card_id)


@router.get("/datasets/{dataset_id}/cards")
def list_cards(dataset: sqlite3.Row = Depends(owned_dataset), db: sqlite3.Connection = Depends(get_db)) -> list[dict]:
    """The overview first, then the widget cards in dashboard order, then synthesis and answer cards
    oldest first."""
    rows = db.execute(
        "SELECT c.* FROM cards c LEFT JOIN widgets w ON w.id = c.widget_id WHERE c.dataset_id = ? AND c.deleted_at IS NULL "
        "ORDER BY c.kind != 'overview', c.widget_id IS NULL, w.order_no, c.created_at", (dataset["id"],)).fetchall()
    return [stories.to_card(db, r) for r in rows]


@router.get("/cards/{cid}")
def get_card(cid: str, _: Owned = Depends(owned("card")), db: sqlite3.Connection = Depends(get_db)) -> dict:
    return stories.to_card(db, _card(db, cid))


@router.patch("/cards/{cid}")
def edit_card(cid: str, body: CardEdit, request: Request, _: Owned = Depends(owned("card")),
              db: sqlite3.Connection = Depends(get_db)) -> dict:
    """The user's own text. Numbers typed by hand become unverified chips, a chip shows its fact's
    value from the sheet (one whose fact isn't there is unverified), and the card is never narrated
    over again, only offered suggestions (PRD STORY-7). Its `version` becomes the one its words were
    written on, the version of the sheet its chips read (the web's "Written on vN" badge, plan 2b.7)."""
    sets = ["edited_by_user = 1", "updated_at = ?",
            "version = COALESCE((SELECT version FROM fact_sheets WHERE id = cards.fact_sheet_id), version)"]
    params = [now_iso()]
    card = _card(db, cid)
    for key in ("headline", "body"):
        value = getattr(body, key)
        if value is not None:
            if not isinstance(value.get("blocks"), list):
                raise ApiError(422, "invalid", f"{key}: expected {{blocks: [...]}}")
            sets.append(f"{key}_json = ?")
            params.append(json.dumps(stories.checked_edit(db, card, value)))
    db.execute(f"UPDATE cards SET {', '.join(sets)} WHERE id = ?", (*params, cid))  # noqa: S608
    return _changed(request, db, cid)


@router.post("/cards/{cid}/refresh", status_code=201)
def refresh_card(cid: str, request: Request, _: Owned = Depends(owned("card")), db: sqlite3.Connection = Depends(get_db)) -> dict:
    from sherlock.jobs.runner import insert_job, to_job

    r = _card(db, cid)
    dataset = _dataset(db, r["dataset_id"])
    if r["kind"] in ("synthesis", "answer") and not r["widget_id"]:
        ids = "answer_ids" if r["kind"] == "answer" else "synthesis_ids"  # an answer re-runs its queries (plan 2b.2)
        job = insert_job(db, dataset["user_id"], dataset["id"], "stories", {ids: [cid], "reason": "refresh"})
        request.app.state.jobs.wake()
        return to_job(job)
    queue_stories(db, dataset, [r["widget_id"]] if r["widget_id"] else [], "refresh")
    request.app.state.jobs.wake()
    job = db.execute("SELECT * FROM jobs WHERE dataset_id = ? AND kind = 'stories' ORDER BY created_at DESC LIMIT 1",
                     (dataset["id"],)).fetchone()
    return to_job(job)


@router.post("/cards/{cid}/accept-suggestion")
def accept_suggestion(cid: str, request: Request, _: Owned = Depends(owned("card")), db: sqlite3.Connection = Depends(get_db)) -> dict:
    r = _card(db, cid)
    if not r["suggestion_json"]:
        raise ApiError(409, "conflict", "This card has no suggestion.")
    s = json.loads(r["suggestion_json"])
    # The suggestion was written from the card's current sheet, so the card now reflects its version.
    db.execute("UPDATE cards SET headline_json = ?, body_json = ?, suggestion_json = NULL, edited_by_user = 0, "
               "changed_badge = 0, version = COALESCE((SELECT version FROM fact_sheets WHERE id = cards.fact_sheet_id), "
               "version), updated_at = ? WHERE id = ?",
               (json.dumps(s["headline"]), json.dumps(s["body"]), now_iso(), cid))
    return _changed(request, db, cid)


@router.post("/cards/{cid}/dismiss-suggestion")
def dismiss_suggestion(cid: str, request: Request, _: Owned = Depends(owned("card")), db: sqlite3.Connection = Depends(get_db)) -> dict:
    db.execute("UPDATE cards SET suggestion_json = NULL, changed_badge = 0, updated_at = ? WHERE id = ?", (now_iso(), cid))
    return _changed(request, db, cid)


@router.post("/cards/{cid}/dismiss-badge")
def dismiss_badge(cid: str, request: Request, _: Owned = Depends(owned("card")), db: sqlite3.Connection = Depends(get_db)) -> dict:
    db.execute("UPDATE cards SET changed_badge = 0 WHERE id = ?", (cid,))
    return _changed(request, db, cid)


@router.delete("/cards/{cid}", status_code=204)
def delete_card(cid: str, request: Request, _: Owned = Depends(owned("card")), db: sqlite3.Connection = Depends(get_db)) -> None:
    db.execute("UPDATE cards SET deleted_at = ? WHERE id = ?", (now_iso(), cid))
    r = _card(db, cid)
    db.execute("UPDATE datasets SET state_rev = state_rev + 1 WHERE id = ?", (r["dataset_id"],))  # a new export key (plan 1.4)
    dataset = _dataset(db, r["dataset_id"])
    stories.emit_card(db, request.app.state.bus, dataset, cid)
    # A synthesis citing it can no longer show its numbers: `sources_changed`, with Refresh (plan 1.3).
    synthesis.check_sources(db, request.app.state.bus, dataset)


@router.post("/cards/{cid}/restore")
def restore_card(cid: str, request: Request, db: sqlite3.Connection = Depends(get_db), _: Owned = Depends(owned("card"))) -> dict:
    db.execute("UPDATE cards SET deleted_at = NULL WHERE id = ?", (cid,))
    return _changed(request, db, cid)


@router.get("/fact-sheets/{fsid}")
def get_fact_sheet(fsid: str, _: Owned = Depends(owned("fact_sheet")), db: sqlite3.Connection = Depends(get_db)) -> dict:
    sheet = stories.get_sheet(db, fsid)
    if sheet is None:
        raise not_found("Fact sheet not found")
    return sheet


@router.get("/cards/{cid}/evidence/{chip_id}")
def evidence(cid: str, chip_id: str, _: Owned = Depends(owned("card")), db: sqlite3.Connection = Depends(get_db)) -> dict:
    """What a chip stands on: the fact's query (or how it was derived), its value and version."""
    card = stories.to_card(db, _card(db, cid))
    chip = stories.find_chip(card, chip_id)
    if chip is None:
        raise not_found("Chip not found")
    if chip.get("unverified"):
        return {"value": chip["value"], "unverified": True, "label": "Typed by you, not computed", "version": card["version"]}
    sheet = stories.get_sheet(db, card["fact_sheet_id"])
    f = (sheet or {}).get("facts", {}).get(chip["key"])
    via = None
    if f is None and sheet is None and "." in (chip["key"] or ""):
        # A synthesis or answer card's chip resolves through the card it cites (TRD §7.4.1).
        source = stories.card_row(db, chip["key"].partition(".")[0])
        sheet = stories.get_sheet(db, source["fact_sheet_id"]) if source["dataset_id"] == card["dataset_id"] else None
        f = (sheet or {}).get("facts", {}).get(chip["key"].partition(".")[2])
        via = source["id"]
    if f is None:
        raise not_found("This number's fact is no longer on the card's fact sheet.")
    return {"key": chip["key"], "value": f["value"], "formatted": f["formatted"], "label": f["label"],
            "sql": f.get("sql"), "cell": f.get("cell"), "from": f.get("from"), "formula": f.get("formula"),
            "method": f.get("method"), "run_id": f.get("run_id"), "computed_at": sheet["computed_at"],
            "version": sheet["version"], "card_id": via}


@router.get("/datasets/{dataset_id}/relations")
def get_relations(dataset: sqlite3.Row = Depends(owned_dataset), db: sqlite3.Connection = Depends(get_db)) -> dict:
    rows = db.execute("SELECT * FROM relations WHERE dataset_id = ? AND version = (SELECT max(version) FROM relations "
                      "WHERE dataset_id = ?)", (dataset["id"], dataset["id"])).fetchall()
    return {"edges": [{"a": r["a_widget"], "b": r["b_widget"], "kind": r["kind"], "weight": r["weight"],
                       "detail": json.loads(r["detail_json"]) if r["detail_json"] else None} for r in rows]}
