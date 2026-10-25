"""ML recipes and runs (TRD §4.8). With cuts 4 and 7 only `driver_analysis` with Auto runs; the other
recipes are listed disabled with their reason."""

import json
import sqlite3

from fastapi import APIRouter, Body, Depends, Query, Request, Response, status

from sherlock.db.connection import get_db
from sherlock.db.users import User
from sherlock.errors import ApiError, not_found
from sherlock.identity import current_user
from sherlock.jobs.runner import cancel_job
from sherlock.ml import registry
from sherlock.ml import runner as ml
from sherlock.ownership import Owned, check_dataset, owned, owned_dataset
from sherlock.widgets import service as ws

router = APIRouter(tags=["ml"])


def _env(request: Request, db: sqlite3.Connection) -> ws.Env:
    return ws.Env(request.app.state.settings, db, request.app.state.duckdb, request.app.state.bus)


def _run(owned_run: Owned, user: User, db: sqlite3.Connection) -> tuple[sqlite3.Row, sqlite3.Row]:
    dataset = check_dataset(db, user.id, owned_run.dataset_id)
    return dataset, ml.get_run(db, owned_run.id)


@router.get("/recipes")
def recipes(
    request: Request,
    dataset_id: str = Query(...),
    scope: str | None = None,
    user: User = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> list[dict]:
    """Every recipe's manifest with `compatible` and, when not, the `reason` (PRD ML-1). Rows are
    counted in the scope (quarantine excluded)."""
    dataset = check_dataset(db, user.id, dataset_id)
    env = _env(request, db)
    version = dataset["current_version"]
    card = ml.datacard(env, dataset, version)
    try:
        raw = json.loads(scope) if scope else None
    except ValueError:
        raise ApiError(422, "invalid", "scope: not valid JSON") from None
    parsed = ml.parse_request({"scope": raw})
    where = ml.rows_sql(env, dataset, parsed["scope"], version)
    with ws.connection(env, dataset, version) as conn:
        rows = conn.execute(f"SELECT count(*) FROM t WHERE {where}").fetchone()[0]  # noqa: S608
    return registry.manifests(card, rows)


@router.post("/datasets/{dataset_id}/runs")
def create_run(
    request: Request,
    body: dict = Body(...),
    dataset: sqlite3.Row = Depends(owned_dataset),
    user: User = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Start a run, or return the cached one (`status: done` at once). With `widget_id` the widget
    becomes the analysis (its chart is kept for Undo / "Plain chart")."""
    req = ml.parse_request(body)
    env = _env(request, db)
    if req["widget_id"]:
        row = ws.get_row(db, req["widget_id"])
        if row["dataset_id"] != dataset["id"] or row["deleted_at"]:
            raise not_found("Widget not found")
        p = ml.prepare(env, dataset, req)
        view = json.loads(row["spec_json"])["view"]["type"] if json.loads(row["spec_json"])["op"]["type"] == "ml" else "importance"
        new = ws.update(env, dataset, row, ml.ml_spec(p, view), None)
        run = ml.get_run(db, new["run_id"])
    else:
        run = ml.launch(env, dataset, ml.prepare(env, dataset, req), "user")
    request.app.state.jobs.wake()
    return ml.to_run(db, run, full=True)


@router.post("/datasets/{dataset_id}/runs/preview")
def preview_run(
    request: Request,
    body: dict = Body(...),
    dataset: sqlite3.Row = Depends(owned_dataset),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """What the setup form shows: task, columns with exclusion reasons, baselines, estimate."""
    return ml.preview(_env(request, db), dataset, ml.parse_request(body))


@router.get("/runs/{rid}")
def get_run(owned_run: Owned = Depends(owned("run")), user: User = Depends(current_user),
            db: sqlite3.Connection = Depends(get_db)) -> dict:
    _, run = _run(owned_run, user, db)
    return ml.to_run(db, run, full=True)


@router.post("/runs/{rid}/cancel", status_code=status.HTTP_204_NO_CONTENT)
def cancel_run(request: Request, owned_run: Owned = Depends(owned("run")), user: User = Depends(current_user),
               db: sqlite3.Connection = Depends(get_db)) -> Response:
    _, run = _run(owned_run, user, db)
    if run["status"] in ml.RUNNING and run["job_id"]:
        cancel_job(db, request.app.state.bus, run["job_id"])
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/runs/{rid}/results")
def run_results(
    request: Request,
    view: str = "importance",
    feature: str | None = None,
    owned_run: Owned = Depends(owned("run")),
    user: User = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    dataset, run = _run(owned_run, user, db)
    return ml.results(request.app.state.settings, db, dataset, run, view, feature)


@router.get("/runs/{rid}/model-card")
def model_card(owned_run: Owned = Depends(owned("run")), user: User = Depends(current_user),
               db: sqlite3.Connection = Depends(get_db)) -> dict:
    _, run = _run(owned_run, user, db)
    if not run["model_card_json"]:
        raise ApiError(409, "conflict", "The analysis hasn't finished yet." if run["status"] in ml.RUNNING
                       else "This run has no model card.")
    return {**json.loads(run["model_card_json"]), "status": run["status"]}


@router.get("/runs/{rid}/code")
def run_code(request: Request, owned_run: Owned = Depends(owned("run")), user: User = Depends(current_user),
             db: sqlite3.Connection = Depends(get_db)) -> dict:
    """The run's `repro.py` (TRD §6.7), written when it finished."""
    dataset, run = _run(owned_run, user, db)
    if not run["repro_path"]:
        raise ApiError(409, "conflict", "The reproduction code is written when the analysis finishes.")
    path = ml.run_folder(request.app.state.settings, dataset, run["id"]) / "repro.py"
    return {"python": path.read_text(encoding="utf-8")}


@router.post("/runs/{rid}/wrong-rows", status_code=status.HTTP_201_CREATED)
def run_wrong_rows(request: Request, owned_run: Owned = Depends(owned("run")), user: User = Depends(current_user),
                   db: sqlite3.Connection = Depends(get_db)) -> dict:
    """"Who did it get wrong?": a selection of the misclassified rows (out of fold), opened in the CSV
    tab with `?rows=<selection_id>`."""
    dataset, run = _run(owned_run, user, db)
    return ml.wrong_rows(db, request.app.state.settings, dataset, run)


@router.post("/widgets/{wid}/rerun")
def rerun_widget(request: Request, owned_widget: Owned = Depends(owned("widget")), user: User = Depends(current_user),
                 db: sqlite3.Connection = Depends(get_db)) -> dict:
    """Re-run an analysis widget on the current version (its "Outdated" footer, App Flow §9 step 6)."""
    dataset = check_dataset(db, user.id, owned_widget.dataset_id)
    row = ws.get_row(db, owned_widget.id)
    if row["deleted_at"] or json.loads(row["spec_json"])["op"]["type"] != "ml":
        raise ApiError(422, "invalid", "Only an analysis widget can be re-run.")
    env = _env(request, db)
    run = ml.rerun_widget(env, dataset, row)
    ws._emit(env, dataset, ws.get_row(db, row["id"]))
    request.app.state.jobs.wake()
    return ml.to_run(db, run, full=True)
