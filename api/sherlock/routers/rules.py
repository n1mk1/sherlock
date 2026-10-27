"""Checks you write (TRD §4.4, PRD CLEAN-13): a dataset's rules, each with its count on the current
version, computed by code when it's read or saved."""

import sqlite3
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict

from sherlock.cleaning.rules import interpreter
from sherlock.cleaning.rules import service as rules
from sherlock.cleaning.rules import store
from sherlock.cleaning.rules.kinds import RuleError
from sherlock.db.connection import get_db
from sherlock.errors import ApiError
from sherlock.ownership import Owned, owned, owned_dataset

router = APIRouter(tags=["rules"])
KIND = Literal["range", "date_window", "allowed", "pattern", "not_missing", "unique", "order", "depends"]
ACTION = Literal["quarantine", "flag", "fix"]


class RuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: KIND
    column: str
    params: dict[str, Any] = {}
    action: ACTION = "flag"
    scope: Literal["dataset", "all"] = "dataset"  # "all": your check for every dataset (P2)


class RulePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["active", "off"] | None = None
    params: dict[str, Any] | None = None
    action: ACTION | None = None


def invalid(exc: RuleError) -> ApiError:
    return ApiError(422, "invalid", f"{exc.field}: {exc}")


def _env(request: Request):
    s = request.app.state
    return s.settings, s.duckdb, s.bus


@router.get("/datasets/{dataset_id}/rules")
def list_rules(request: Request, dataset: sqlite3.Row = Depends(owned_dataset), db: sqlite3.Connection = Depends(get_db)) -> dict:
    settings, cache, _ = _env(request)
    return {"rules": rules.with_counts(settings, db, cache, dataset, store.all_for(db, dataset["id"]))}


@router.post("/datasets/{dataset_id}/rules", status_code=status.HTTP_201_CREATED)
def add_rule(request: Request, body: RuleIn, dataset: sqlite3.Row = Depends(owned_dataset),
             db: sqlite3.Connection = Depends(get_db)) -> dict:
    """Save a check: validated against the file's columns (422 names the bad field), run on the
    current version, and added to an open plan."""
    settings, cache, bus = _env(request)
    try:
        rule = rules.add(settings, db, cache, bus, dataset, body.model_dump(exclude={"scope"}),
                         every_dataset=body.scope == "all")
    except RuleError as exc:
        raise invalid(exc) from None
    return rules.with_counts(settings, db, cache, dataset, [rule])[0]


@router.patch("/rules/{rid}")
def patch_rule(request: Request, body: RulePatch, owned_rule: Owned = Depends(owned("rule")),
               db: sqlite3.Connection = Depends(get_db)) -> dict:
    settings, cache, bus = _env(request)
    rule = store.get(db, owned_rule.id)
    dataset = db.execute("SELECT * FROM datasets WHERE id = ?", (owned_rule.dataset_id,)).fetchone()
    if dataset is None:  # a check for every dataset: switched on or off, then each dataset's next profile runs it
        if body.params is not None or body.action is not None:
            raise invalid(RuleError("scope", "A check for every dataset can be switched on or off; to change it, add it again."))
        if body.status is not None:
            store.update(db, rule["id"], status=body.status)
        return {**store.get(db, rule["id"]), "words": interpreter.words(rule), "count": None, "error": None}
    try:
        rule = rules.change(settings, db, cache, bus, dataset, rule, body.params, body.action, body.status)
    except RuleError as exc:
        raise invalid(exc) from None
    return rules.with_counts(settings, db, cache, dataset, [rule])[0]
