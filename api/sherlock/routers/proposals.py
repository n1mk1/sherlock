"""Proposals from chat (TRD §4.4): approve or reject a change the chat proposed (PRD ASK-10)."""

import sqlite3

from fastapi import APIRouter, Body, Depends, Request, Response, status

from sherlock.agent import actions
from sherlock.db.connection import get_db
from sherlock.ownership import Owned, owned

router = APIRouter(tags=["chat"])


def _rows(db: sqlite3.Connection, owned_proposal: Owned) -> tuple[sqlite3.Row, sqlite3.Row]:
    row = db.execute("SELECT * FROM proposals WHERE id = ?", (owned_proposal.id,)).fetchone()
    dataset = db.execute("SELECT * FROM datasets WHERE id = ?", (row["dataset_id"],)).fetchone()
    return row, dataset


@router.get("/proposals/{id}")
def get_proposal(owned_proposal: Owned = Depends(owned("proposal")), db: sqlite3.Connection = Depends(get_db)) -> dict:
    return actions.to_proposal(_rows(db, owned_proposal)[0])


@router.post("/proposals/{id}/approve")
def approve(request: Request, body: dict | None = Body(default=None), owned_proposal: Owned = Depends(owned("proposal")),
            db: sqlite3.Connection = Depends(get_db)) -> dict:
    """`{ step, version }` for cell edits, the clean `Job` for a selection; `409` when the data moved on
    (the proposal expires) or it was already decided. `edited_code` is for P1 code proposals."""
    row, dataset = _rows(db, owned_proposal)
    return actions.approve(request.app, db, dataset, row)


@router.post("/proposals/{id}/reject", status_code=status.HTTP_204_NO_CONTENT)
def reject(owned_proposal: Owned = Depends(owned("proposal")), db: sqlite3.Connection = Depends(get_db)) -> Response:
    actions.reject(db, _rows(db, owned_proposal)[0])
    return Response(status_code=status.HTTP_204_NO_CONTENT)
