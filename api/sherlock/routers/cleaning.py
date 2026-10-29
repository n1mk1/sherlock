"""Cleaning (TRD §4.4): the detector catalog, the cleaning plan, start a clean, use the data as is,
read the report."""

import json
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field

from sherlock.cleaning import plan as plans
from sherlock.cleaning import registry, review
from sherlock.cleaning.report import build_report
from sherlock.cleaning.rules import service as rule_service
from sherlock.cleaning.rules.kinds import RuleError
from sherlock.db.connection import get_db
from sherlock.errors import ApiError, not_found
from sherlock.db import datasets as datasets_repo
from sherlock.db import users
from sherlock.jobs.clean import mark_ready
from sherlock.jobs.events import emit
from sherlock.jobs.runner import to_job
from sherlock.ownership import Owned, owned, owned_dataset
from sherlock.profile import service as profile_service
from sherlock.ratelimit import llm_rate_limit
from sherlock.routers.datasets import Dataset, to_dataset
from sherlock.routers.me import effective_settings
from sherlock.routers.rules import RuleIn
from sherlock.query import context as qx

router = APIRouter(tags=["cleaning"])
STARTABLE = ("offer", "ready")
PLANNABLE = ("offer", "ready")


class CleanScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["all", "selection", "new_rows"] = "all"
    selection_id: str | None = None
    row_ids: list[int] | None = None


class CleanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["auto", "stepwise"] = "auto"
    scope: CleanScope = Field(default_factory=CleanScope)
    include_user_edited: bool = False
    plan_id: str | None = None  # a draft cleaning plan: run what it ticks (PRD CLEAN-8a)
    # The plan items the user saw ticked: when the plan's own differ (the review or chat changed it as Start
    # was pressed), it's shown again instead of run.
    ticked: list[str] | None = None


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: CleanScope | None = None  # the rows the plan is for: the new-rows toast, chat's clean_selection
    depth: Literal[1, 2, 3, 4, 5] | None = None  # the layers it lists (PRD CLEAN-15); null: the user's setting


class PlanOp(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["tick", "untick", "tick_module", "untick_module", "tick_level", "untick_level", "set_instruction",
                "set_date_order", "add", "remove", "add_rule", "keep_suggestion", "dismiss_suggestion"]
    item_id: str | None = None
    module: str | None = None
    level: Literal["breaks", "skews", "splits", "check", "cosmetic"] | None = None  # tick_level, untick_level
    rule: RuleIn | None = None  # add_rule: a check of your own (PRD CLEAN-13)
    rule_id: str | None = None  # keep_suggestion, dismiss_suggestion (PRD CLEAN-14)
    column: str | None = None  # add: a column of the file, or null for the rows
    instruction: str | None = Field(default=None, max_length=plans.MAX_INSTRUCTION)  # null on set_instruction resets
    order: Literal["dmy", "mdy"] | None = None  # set_date_order: day-first or month-first; null clears it


class PlanPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ops: list[PlanOp] = Field(min_length=1, max_length=50)


class Detector(BaseModel):
    id: str
    label: str
    description: str
    group: str
    default_level: Literal["breaks", "skews", "splits", "check", "cosmetic"] | None
    depth: int  # its layer, 1–5 (PRD CLEAN-15)
    source: str  # "builtin"


class Detectors(BaseModel):
    detectors: list[Detector]


@router.get("/detectors", response_model=Detectors)
def list_detectors() -> Detectors:
    """The detector catalog (PRD CLEAN-12): every registered check's id, plain-words label and group."""
    return Detectors(detectors=[Detector(**d) for d in registry.catalog()])


def _busy(db: sqlite3.Connection, dataset_id: str) -> bool:
    return db.execute(
        "SELECT 1 FROM jobs WHERE dataset_id = ? AND kind IN ('profile', 'clean') "
        "AND status IN ('queued', 'running') LIMIT 1", (dataset_id,),
    ).fetchone() is not None


@router.post("/datasets/{dataset_id}/clean", status_code=status.HTTP_201_CREATED, dependencies=[Depends(llm_rate_limit)])
def start_clean(
    body: CleanRequest,
    request: Request,
    dataset: sqlite3.Row = Depends(owned_dataset),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Queue a clean job on the current version. With `plan_id`, the job runs that draft plan: its
    items are frozen into the job's params and the plan becomes `started`; with `ticked`, a plan whose
    ticked items differ answers 409 with the plan instead. Step-by-step mode is P1 (PRD CLEAN-10)."""
    if body.mode == "stepwise":
        raise ApiError(422, "invalid", "Step-by-step cleaning isn't available yet. Use auto.")
    if body.scope.kind == "selection" and not body.scope.selection_id:
        raise ApiError(422, "invalid", "scope: a selection scope needs selection_id")
    if dataset["status"] not in STARTABLE:
        raise ApiError(409, "conflict", f"This CSV is {dataset['status']}; cleaning can start once that finishes.")
    if _busy(db, dataset["id"]):
        raise ApiError(409, "conflict", "A job is already running on this CSV.")
    params = body.model_dump(exclude={"plan_id"})
    row = None
    if body.plan_id:
        row = plans.get(db, body.plan_id)
        if row is None or row["dataset_id"] != dataset["id"]:
            raise not_found("Cleaning plan not found")
        if row["status"] != "draft":
            raise ApiError(409, "conflict", f"This plan was already {row['status']}.")
        if row["version"] != dataset["current_version"]:
            merged, notes = plans.current(db, row, dataset, lambda d: _card(request, db, d))
            _plan_event(request, db, dataset, row["id"])
            raise ApiError(409, "conflict", "The data changed since the plan was made, so it was checked again. "
                           "Look it over, then start.", extra={"plan": _out(request.app, db, merged, notes)})
        items = json.loads(row["items_json"])
        if body.ticked is not None and sorted(body.ticked) != sorted(i["id"] for i in plans.ticked(items)):
            raise ApiError(409, "conflict", "The plan changed as you pressed Start. Look it over, then start.",
                           extra={"plan": _out(request.app, db, row)})
        if not plans.ticked(items):
            raise ApiError(422, "invalid", "Nothing in the plan is ticked, so there's nothing to clean.")
        params["plan"] = {"id": row["id"], "version": row["version"], "items": items, "depth": row["depth"]}
    job = request.app.state.jobs.enqueue(db, dataset["user_id"], dataset["id"], "clean", params)
    if row is not None:
        plans.set_status(db, row["id"], "started", job["id"])
        _plan_event(request, db, dataset, row["id"])
    return to_job(job)


# --- the cleaning plan (PRD CLEAN-8a, CLEAN-8b) ----------------------------------------------------


def _out(app, db: sqlite3.Connection, row: sqlite3.Row, notes: list[str] | None = None) -> dict:
    """The `CleanPlan` with its version's review status and suggested checks (TRD §4.4)."""
    s = app.state
    dataset = db.execute("SELECT * FROM datasets WHERE id = ?", (row["dataset_id"],)).fetchone()
    return {**plans.to_plan(row, notes, review.status(s.settings, db, row["dataset_id"], row["version"])),
            "suggestions": rule_service.suggestions(s.settings, db, s.duckdb, dataset, row["version"])}


def _card(request: Request, db: sqlite3.Connection, dataset: sqlite3.Row) -> dict:
    return profile_service.get_or_build(request.app.state.settings, db, request.app.state.duckdb, dataset)


def _plan_event(request: Request, db: sqlite3.Connection, dataset: sqlite3.Row, plan_id: str) -> None:
    emit(db, request.app.state.bus, dataset["id"], dataset["user_id"], "plan.updated", {"plan_id": plan_id})


def plan_scope(env: qx.Env, dataset: sqlite3.Row, scope: CleanScope | None) -> dict | None:
    """A plan's stored scope with its row count (a selection's counted on the current version),
    or None for the whole dataset."""
    if scope is None or scope.kind == "all":
        return None
    if scope.kind == "selection":
        rows = qx.selection_rows(env, dataset, scope.selection_id or "")
        if rows is None:
            raise ApiError(422, "invalid", "scope: that selection isn't one of this CSV's")
        return {"kind": "selection", "selection_id": scope.selection_id, "row_ids": None, "rows": rows}
    row_ids = sorted({int(i) for i in scope.row_ids}) if scope.row_ids else None
    return {"kind": "new_rows", "selection_id": None, "row_ids": row_ids, "rows": len(row_ids) if row_ids else None}


def open_plan(app, db: sqlite3.Connection, dataset: sqlite3.Row, scope: CleanScope | None = None,
              depth: int | None = None) -> tuple[dict, bool]:
    """Get or create the dataset's draft plan on the current version (PRD CLEAN-8a), with `scope` and
    `depth` when given. A new plan without a depth takes the user's Cleaning depth setting (PRD CLEAN-15).
    Returns the `CleanPlan` and whether it was made now. Nothing is cleaned until Start."""
    if dataset["status"] not in PLANNABLE:
        raise ApiError(409, "conflict", f"This CSV is {dataset['status']}; a cleaning plan can be made once that finishes.")
    stored = plan_scope(qx.Env(app.state.settings, db, app.state.duckdb, app.state.bus), dataset, scope)
    card = lambda d: profile_service.get_or_build(app.state.settings, db, app.state.duckdb, d)  # noqa: E731
    existing = plans.draft_id(db, dataset["id"])
    if existing:
        row, notes = plans.current(db, plans.get(db, existing), dataset, card)
        changed = bool(notes)
    else:
        if depth is None:
            user = users.get(db, dataset["user_id"])
            depth = effective_settings(user.settings if user else {}).clean_depth
        row, notes, changed = plans.create(db, dataset, card(dataset), depth=depth), [], True
    if depth is not None and depth != row["depth"]:
        row, changed = plans.set_depth(db, row, card(dataset), depth), True
    if scope is not None:
        row, changed = plans.set_scope(db, row["id"], stored), True
    if changed:
        emit(db, app.state.bus, dataset["id"], dataset["user_id"], "plan.updated", {"plan_id": row["id"]})
    if review.queue(app.state.settings, db, dataset, row["version"]):  # a version never reviewed (TRD §7.2)
        app.state.jobs.wake()
    return _out(app, db, row, notes), existing is None


def _owned_plan(owned_plan: Owned, db: sqlite3.Connection) -> tuple[sqlite3.Row, sqlite3.Row]:
    row = plans.get(db, owned_plan.id)
    dataset = db.execute("SELECT * FROM datasets WHERE id = ?", (row["dataset_id"],)).fetchone()
    return row, dataset


@router.post("/datasets/{dataset_id}/clean/plan", status_code=status.HTTP_201_CREATED)
def create_plan(
    request: Request,
    response: Response,
    body: PlanRequest | None = None,
    dataset: sqlite3.Row = Depends(owned_dataset),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Get or create the draft plan for the current version (merged onto it when it's older).
    Answers 201 for a new plan, 200 for the existing draft. With `scope` (the new-rows toast's "Clean
    them"), the plan is for those rows; without it, a draft keeps the scope it has. With `depth` (the
    offer's slider), it lists the layers up to that depth; without it, a draft keeps its depth."""
    plan, created = open_plan(request.app, db, dataset, body.scope if body else None, body.depth if body else None)
    if not created:
        response.status_code = status.HTTP_200_OK
    return plan


@router.get("/clean-plans/{pid}")
def get_plan(request: Request, owned_plan: Owned = Depends(owned("clean_plan")), db: sqlite3.Connection = Depends(get_db)) -> dict:
    """The plan; a draft made on an older version is merged onto the current one first."""
    row, dataset = _owned_plan(owned_plan, db)
    row, notes = plans.current(db, row, dataset, lambda d: _card(request, db, d))
    return _out(request.app, db, row, notes)


@router.patch("/clean-plans/{pid}")
def patch_plan(
    body: PlanPatch,
    request: Request,
    owned_plan: Owned = Depends(owned("clean_plan")),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Apply ops, all or nothing. The answer is the plan with a code-written `summary` of the change."""
    row, dataset = _owned_plan(owned_plan, db)
    if row["status"] != "draft":
        raise ApiError(409, "conflict", f"This plan was already {row['status']}.")
    row, notes = plans.current(db, row, dataset, lambda d: _card(request, db, d))
    env = qx.Env(request.app.state.settings, db, request.app.state.duckdb, request.app.state.bus)
    columns = list(qx.user_types(env, dataset, dataset["current_version"]))
    try:
        row, summary = rule_service.apply(env.settings, db, env.cache, env.bus, dataset, row,
                                          [o.model_dump() for o in body.ops], columns)
    except RuleError as exc:
        raise ApiError(422, "invalid", f"rule.{exc.field}: {exc}") from None
    except plans.PlanError as exc:
        raise ApiError(422, "invalid", str(exc)) from None
    _plan_event(request, db, dataset, row["id"])
    return {**_out(request.app, db, row, notes), "summary": summary}


@router.delete("/clean-plans/{pid}", status_code=status.HTTP_204_NO_CONTENT)
def discard_plan(request: Request, owned_plan: Owned = Depends(owned("clean_plan")), db: sqlite3.Connection = Depends(get_db)) -> Response:
    """Discard a draft; the offer (or the Changes panel) shows again."""
    row, dataset = _owned_plan(owned_plan, db)
    if row["status"] == "draft":
        plans.set_status(db, row["id"], "discarded")
        _plan_event(request, db, dataset, row["id"])
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/datasets/{dataset_id}/use-as-is", response_model=Dataset)
def use_as_is(
    request: Request,
    dataset: sqlite3.Row = Depends(owned_dataset),
    db: sqlite3.Connection = Depends(get_db),
) -> Dataset:
    """Skip cleaning ("Clean it myself"): the current (typed) version is ready as it is. A draft
    cleaning plan is discarded. Returns the dataset."""
    if dataset["status"] != "offer":
        raise ApiError(409, "conflict", f"This CSV is {dataset['status']}, not waiting for a choice.")
    if _busy(db, dataset["id"]):
        raise ApiError(409, "conflict", "A job is already running on this CSV.")
    plans.discard_drafts(db, dataset["id"])
    mark_ready(db, request.app.state.bus, dataset["id"])
    return to_dataset(datasets_repo.get(db, dataset["user_id"], dataset["id"]), db)


@router.get("/datasets/{dataset_id}/report")
def report(
    job_id: str | None = Query(default=None),
    dataset: sqlite3.Row = Depends(owned_dataset),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    return build_report(db, dataset["id"], job_id)
