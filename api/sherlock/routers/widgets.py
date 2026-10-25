"""Widgets and layout (TRD §4.5), and row selections (TRD §4.3)."""

import json
import sqlite3

from fastapi import APIRouter, Body, Depends, Query, Request, Response, status

from sherlock.db.connection import get_db
from sherlock.db.users import User
from sherlock.db.util import new_id, now_iso
from sherlock.errors import ApiError, not_found
from sherlock.identity import current_user
from sherlock.jobs.events import emit
from sherlock.ownership import Owned, check_dataset, owned, owned_dataset
from sherlock.widgets import compile as wc
from sherlock.widgets import layout as wl
from sherlock.widgets import service as ws
from sherlock.widgets.spec import merge

router = APIRouter(tags=["widgets"])


def _env(request: Request, db: sqlite3.Connection) -> ws.Env:
    return ws.Env(request.app.state.settings, db, request.app.state.duckdb, request.app.state.bus)


def _live(db: sqlite3.Connection, dataset_id: str) -> list[sqlite3.Row]:
    return db.execute(
        "SELECT * FROM widgets WHERE dataset_id = ? AND deleted_at IS NULL ORDER BY order_no", (dataset_id,)
    ).fetchall()


def _views(rows: list[sqlite3.Row]) -> list[tuple[str, str]]:
    return [(r["id"], json.loads(r["spec_json"])["view"]["type"]) for r in rows]


def _widget(owned_widget: Owned, user: User, db: sqlite3.Connection, allow_deleted: bool = False):
    dataset = check_dataset(db, user.id, owned_widget.dataset_id)
    row = ws.get_row(db, owned_widget.id)
    if row["deleted_at"] and not allow_deleted:
        raise not_found("Widget not found")
    return dataset, row


def _place(db: sqlite3.Connection, dataset_id: str, row: sqlite3.Row) -> None:
    """Put a new widget under the others in the saved layout (an unsaved layout is packed on read)."""
    saved = wl.stored(db, dataset_id)
    if saved is not None:
        wl.save(db, dataset_id, wl.append(saved, row["id"], json.loads(row["spec_json"])["view"]["type"]))


@router.get("/datasets/{dataset_id}/widgets")
def list_widgets(dataset: sqlite3.Row = Depends(owned_dataset), db: sqlite3.Connection = Depends(get_db)) -> dict:
    rows = _live(db, dataset["id"])
    return {"widgets": [ws.to_widget(r) for r in rows], "layout": wl.current(db, dataset["id"], _views(rows))}


@router.post("/datasets/{dataset_id}/widgets", status_code=status.HTTP_201_CREATED)
def create_widget(
    request: Request,
    body: dict = Body(...),
    dataset: sqlite3.Row = Depends(owned_dataset),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """A `WidgetSpec` (optionally with a `title`). The query runs first; a failure is `422`."""
    if "prompt" in body:
        raise ApiError(422, "invalid", "Describing a widget in words needs chat, which isn't built yet.")
    spec = {k: v for k, v in body.items() if k != "title"}
    count = ws.live_count(db, dataset["id"])
    row = ws.create(_env(request, db), dataset, spec, title=body.get("title"), created_by="user")
    _place(db, dataset["id"], row)
    out = {"widget": ws.to_widget(row)}
    if count >= ws.SOFT_CAP:
        out["warning"] = ws.CAP_WARNING
    return out


@router.patch("/widgets/{wid}")
def patch_widget(
    request: Request,
    body: dict = Body(...),
    owned_widget: Owned = Depends(owned("widget")),
    user: User = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """A partial `WidgetSpec` (merged over the current one) and/or a `title`."""
    dataset, row = _widget(owned_widget, user, db)
    if "prompt" in body:
        raise ApiError(422, "invalid", "Changing a widget in words needs chat, which isn't built yet.")
    patch = {k: v for k, v in body.items() if k != "title"}
    spec = merge(json.loads(row["spec_json"]), patch) if patch else None
    return ws.to_widget(ws.update(_env(request, db), dataset, row, spec, body.get("title")))


@router.delete("/widgets/{wid}", status_code=status.HTTP_204_NO_CONTENT)
def delete_widget(
    request: Request,
    owned_widget: Owned = Depends(owned("widget")),
    user: User = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> Response:
    dataset, row = _widget(owned_widget, user, db)
    ws.delete(_env(request, db), dataset, row)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/widgets/{wid}/restore")
def restore_widget(
    request: Request,
    owned_widget: Owned = Depends(owned("widget")),
    user: User = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    dataset, row = _widget(owned_widget, user, db, allow_deleted=True)
    return ws.to_widget(ws.restore(_env(request, db), dataset, row))


@router.post("/widgets/{wid}/duplicate", status_code=status.HTTP_201_CREATED)
def duplicate_widget(
    request: Request,
    owned_widget: Owned = Depends(owned("widget")),
    user: User = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    dataset, row = _widget(owned_widget, user, db)
    copy = ws.create(_env(request, db), dataset, json.loads(row["spec_json"]), title=f"{row['title']} (copy)",
                     created_by="user", point=json.loads(row["point_json"]) if row["point_json"] else None)
    _place(db, dataset["id"], copy)
    return ws.to_widget(copy)


@router.post("/widgets/{wid}/undo")
def undo_widget(
    request: Request,
    owned_widget: Owned = Depends(owned("widget")),
    user: User = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    dataset, row = _widget(owned_widget, user, db)
    return ws.to_widget(ws.undo(_env(request, db), dataset, row))


@router.get("/widgets/{wid}/data")
def widget_data(
    request: Request,
    filters: str | None = None,
    version: int | None = Query(default=None, ge=1),
    owned_widget: Owned = Depends(owned("widget")),
    user: User = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    dataset, row = _widget(owned_widget, user, db)
    return ws.data(_env(request, db), dataset, row, wc.parse_filter(filters), version)


@router.get("/widgets/{wid}/explain")
def widget_explain(
    request: Request,
    filters: str | None = None,
    owned_widget: Owned = Depends(owned("widget")),
    user: User = Depends(current_user),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    dataset, row = _widget(owned_widget, user, db)
    return ws.explain(_env(request, db), dataset, row, wc.parse_filter(filters))


@router.put("/datasets/{dataset_id}/layout")
def put_layout(
    request: Request,
    body: wl.Layout,
    dataset: sqlite3.Row = Depends(owned_dataset),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """Saves the grid. Layout changes never start the cascade (PRD DASH-4)."""
    ids = {r["id"] for r in db.execute("SELECT id FROM widgets WHERE dataset_id = ?", (dataset["id"],))}
    layout = body.model_dump(exclude_none=True)
    for items in layout.values():
        for it in items:
            if it["i"] not in ids:
                raise ApiError(422, "invalid", f"layout: unknown widget {it['i']!r}")
    saved = wl.save(db, dataset["id"], layout)
    ws.bump_state(db, dataset["id"])
    emit(db, request.app.state.bus, dataset["id"], dataset["user_id"], "layout.updated", {"layout": saved})
    return saved


@router.post("/datasets/{dataset_id}/selections", status_code=status.HTTP_201_CREATED)
def create_selection(
    request: Request,
    body: dict = Body(...),
    dataset: sqlite3.Row = Depends(owned_dataset),
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    """A row selection on the current version: a validated predicate or explicit `_row_id`s.
    `row_count` counts rows that aren't quarantined, which is what widgets, ML and chat use."""
    predicate, row_ids, label = body.get("predicate"), body.get("row_ids"), body.get("label")
    if (predicate is None) == (row_ids is None):
        raise ApiError(422, "invalid", "Send either a predicate or row_ids.")
    env = _env(request, db)
    version = dataset["current_version"]
    if predicate is not None:
        if not isinstance(predicate, str):
            raise ApiError(422, "invalid", "predicate: must be text")
        predicate = wc.validate_predicate(predicate, list(ws.user_types(env, dataset, version)))
        where = f"({predicate})"
    else:
        if not isinstance(row_ids, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in row_ids):
            raise ApiError(422, "invalid", "row_ids: must be a list of integers")
        row_ids = sorted(set(row_ids))
        where = f"_row_id IN ({', '.join(str(i) for i in row_ids)})" if row_ids else "FALSE"
    with ws.connection(env, dataset, version) as conn:
        count = conn.execute(f"SELECT count(*) FROM t WHERE _quarantine_reason IS NULL AND {where}").fetchone()[0]
    selection_id = new_id("sel")
    db.execute(
        "INSERT INTO selections (id, dataset_id, version, predicate, row_ids_json, row_count, label, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (selection_id, dataset["id"], version, predicate, json.dumps(row_ids) if row_ids is not None else None,
         count, label if isinstance(label, str) else None, now_iso()),
    )
    return {"selection_id": selection_id, "row_count": count}
