"""Widget rows and their data (TRD §4.5): create, change, delete and restore, compile against a
version, run through the cache. The router, the dashboard builder and the chat agent all use this.

Every widget write bumps `datasets.state_rev` (Schema §2, the export cache key) and emits
`widget.updated` with the `Widget`; a deleted widget's event carries `deleted: true`.
"""

import json
import sqlite3
from dataclasses import dataclass

from pydantic import ValidationError

from sherlock.config import Settings
from sherlock.db.util import new_id, now_iso
from sherlock.errors import ApiError, not_found
from sherlock.jobs.events import EventBus, emit
from sherlock.rows.query import SYSTEM, describe
from sherlock.storage import VersionConnections, dataset_dir
from sherlock.widgets import compile as wc
from sherlock.widgets.execute import CACHE, cache_key, run_query
from sherlock.widgets.spec import WidgetSpec, spec_hash

SOFT_CAP = 20
CAP_WARNING = "This dashboard has 20 or more widgets. Consider removing some so the important ones stand out."


@dataclass
class Env:
    """What widget work needs: settings, one SQLite connection, the DuckDB cache and the event bus."""
    settings: Settings
    db: sqlite3.Connection
    cache: VersionConnections
    bus: EventBus | None


def parse_spec(raw: dict) -> dict:
    """A WidgetSpec as a plain dict, or `422 invalid` with the first schema error."""
    try:
        return WidgetSpec.model_validate(raw).dump()
    except ValidationError as exc:
        err = exc.errors()[0]
        where = ".".join(str(p) for p in err["loc"])
        raise ApiError(422, "invalid", f"spec.{where}: {err['msg']}") from None


def version_row(db: sqlite3.Connection, dataset_id: str, version: int) -> sqlite3.Row:
    row = db.execute("SELECT * FROM versions WHERE dataset_id = ? AND version = ?", (dataset_id, version)).fetchone()
    if row is None:
        raise not_found(f"Version {version} not found")
    return row


def connection(env: Env, dataset: sqlite3.Row, version: int):
    vrow = version_row(env.db, dataset["id"], version)
    folder = dataset_dir(env.settings, dataset["user_id"], dataset["id"])
    return env.cache.connection(dataset["id"], version, folder / vrow["parquet_path"])


def user_types(env: Env, dataset: sqlite3.Row, version: int) -> dict[str, str]:
    with connection(env, dataset, version) as conn:
        return {c: t for c, t in describe(conn).items() if c not in SYSTEM}


def selection_sql(db: sqlite3.Connection, dataset_id: str, selection_id: str) -> str:
    sel = db.execute("SELECT * FROM selections WHERE id = ? AND dataset_id = ?", (selection_id, dataset_id)).fetchone()
    if sel is None:
        raise not_found("Selection not found")
    if sel["row_ids_json"]:
        ids = json.loads(sel["row_ids_json"])
        return f"_row_id IN ({', '.join(str(int(i)) for i in ids)})" if ids else "FALSE"
    return sel["predicate"] or "1=1"


def compiled(env: Env, dataset: sqlite3.Row, spec: dict, version: int, filters: list[dict]) -> str:
    """The exact SQL a SQL widget runs on `version` under the global filter."""
    if spec["op"]["type"] != "sql":
        raise ApiError(422, "invalid", "An analysis widget has no query; its numbers come from its run.")
    types = user_types(env, dataset, version)
    rows = spec["scope"]["rows"]
    predicate = wc.validate_predicate(rows["predicate"], list(types)) if rows.get("predicate") else None
    selection = selection_sql(env.db, dataset["id"], rows["selection_id"]) if rows.get("selection_id") else None
    global_filter = wc.filter_sql(filters, types) if rows.get("inherit_global_filters", True) else None
    return wc.compile_sql(spec["op"]["sql"], wc.rows_clause(predicate, selection, global_filter))


def run_spec(env: Env, dataset: sqlite3.Row, spec: dict, version: int, filters: list[dict] | None = None) -> tuple[str, dict]:
    """(sql, result) for a spec that isn't saved: validation runs and previews."""
    sql = compiled(env, dataset, spec, version, filters or [])
    with connection(env, dataset, version) as conn:
        return sql, run_query(conn, sql)


def to_widget(row: sqlite3.Row) -> dict:
    """A widget in the TRD §4.5 `Widget` shape (plus `error`, `score`, `point`, `deleted_at`)."""
    return {
        "id": row["id"], "dataset_id": row["dataset_id"], "spec": json.loads(row["spec_json"]), "title": row["title"],
        "status": row["status"], "error": row["error"], "run_id": row["run_id"], "created_by": row["created_by"],
        "version_built": row["version_built"], "score": row["score"],
        "point": json.loads(row["point_json"]) if row["point_json"] else None,
        "created_at": row["created_at"], "updated_at": row["updated_at"], "deleted_at": row["deleted_at"],
    }


def get_row(db: sqlite3.Connection, widget_id: str) -> sqlite3.Row:
    row = db.execute("SELECT * FROM widgets WHERE id = ?", (widget_id,)).fetchone()
    if row is None:
        raise not_found("Widget not found")
    return row


def live_count(db: sqlite3.Connection, dataset_id: str) -> int:
    return db.execute("SELECT count(*) FROM widgets WHERE dataset_id = ? AND deleted_at IS NULL", (dataset_id,)).fetchone()[0]


def bump_state(db: sqlite3.Connection, dataset_id: str) -> None:
    db.execute("UPDATE datasets SET state_rev = state_rev + 1 WHERE id = ?", (dataset_id,))


def _emit(env: Env, dataset: sqlite3.Row, row: sqlite3.Row, deleted: bool = False) -> None:
    data = to_widget(row) | ({"deleted": True} if deleted else {})
    emit(env.db, env.bus, dataset["id"], dataset["user_id"], "widget.updated", data)


def templated_title(spec: dict) -> str:
    """A plain title from the spec's columns, for widgets made without one."""
    cols = spec["scope"]["columns"]
    x, y, agg = cols.get("x"), cols.get("y"), cols.get("agg")
    view = spec["view"]["type"]
    if view == "kpi":
        if agg == "count" or not y:
            return "Rows"
        return f"{_agg_word(agg)} {y}"
    if x and y:
        return f"{_agg_word(agg)} {y} by {x}"
    if x:
        return f"Rows by {x}"
    return "Query result"


def analysis_title(spec: dict) -> str:
    return f"What drives {spec['scope']['columns'].get('target')}?"


def _agg_word(agg: str | None) -> str:
    return {"avg": "Average", "sum": "Total", "count": "Count of", "min": "Lowest", "max": "Highest",
            "median": "Median", "rate": "Rate of"}.get(agg or "", "Average")


def create(
    env: Env, dataset: sqlite3.Row, spec: dict, *, title: str | None, created_by: str,
    score: float | None = None, point: dict | None = None, check: bool = True, emit_event: bool = True,
) -> sqlite3.Row:
    """Insert a widget on the current version. With `check`, the query runs first and a failure is
    `422` (nothing saved)."""
    spec = parse_spec(spec)
    version = dataset["current_version"]
    prepared = None
    if spec["op"]["type"] == "ml":
        from sherlock.ml import runner as ml

        prepared = ml.prepare(env, dataset, ml.request_from_spec(spec))  # checks the request; 422 saves nothing
        spec = {**ml.ml_spec(prepared, spec["view"]["type"]), "view": spec["view"]}
    elif check:
        run_spec(env, dataset, spec, version)
    now = now_iso()
    order_no = env.db.execute(
        "SELECT coalesce(max(order_no), 0) + 1 FROM widgets WHERE dataset_id = ?", (dataset["id"],)
    ).fetchone()[0]
    widget_id = new_id("wdg")
    env.db.execute(
        "INSERT INTO widgets (id, dataset_id, title, spec_json, spec_hash, status, version_built, score, point_json, "
        "created_by, order_no, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'ready', ?, ?, ?, ?, ?, ?, ?)",
        (widget_id, dataset["id"], (title or templated_title(spec))[:200], json.dumps(spec), spec_hash(spec), version,
         score, json.dumps(point) if point else None, created_by, order_no, now, now),
    )
    if prepared is not None:
        from sherlock.ml import runner as ml

        ml.link(env.db, widget_id, ml.launch(env, dataset, prepared, created_by, widget_id))
    bump_state(env.db, dataset["id"])
    row = get_row(env.db, widget_id)
    if emit_event:
        _emit(env, dataset, row)
        _stories(env, dataset, [widget_id])
    return row


def _stories(env: Env, dataset: sqlite3.Row, widget_ids: list[str] | None, reason: str = "widget") -> None:
    """A widget added, changed or removed tells its story again (TRD §7.6), once the dashboard
    has stories at all: a card, or a stories job that hasn't stored one yet. (Without the job check,
    an analysis whose run finished before the first card was written never got its own card.)"""
    from sherlock.jobs.stories import queue_stories

    if env.db.execute("SELECT 1 FROM cards WHERE dataset_id = ? UNION ALL SELECT 1 FROM jobs WHERE dataset_id = ? "
                      "AND kind = 'stories' LIMIT 1", (dataset["id"], dataset["id"])).fetchone():
        queue_stories(env.db, dataset, widget_ids, reason)


def update(env: Env, dataset: sqlite3.Row, row: sqlite3.Row, spec: dict | None, title: str | None) -> sqlite3.Row:
    """A new spec and/or title. The old spec goes to `prev_spec_json` for `POST /widgets/{wid}/undo`."""
    sets, params = ["updated_at = ?"], [now_iso()]
    prepared = None
    if spec is not None:
        spec = parse_spec(spec)
        old = json.loads(row["spec_json"])
        if spec["op"]["type"] == "ml":
            from sherlock.ml import runner as ml

            prepared = ml.prepare(env, dataset, ml.request_from_spec(spec))
            spec = {**ml.ml_spec(prepared, spec["view"]["type"]), "view": spec["view"]}
            # A chart that becomes an analysis is titled for it; its own title is kept for "Plain chart".
            chart_title = (old["view"].get("options") or {}).get("chart_title") if old["op"]["type"] == "ml" else row["title"]
            if chart_title:
                spec["view"]["options"] = {**(spec["view"].get("options") or {}), "chart_title": chart_title}
            if old["op"]["type"] != "ml" and title is None:
                title = analysis_title(spec)
        else:
            run_spec(env, dataset, spec, dataset["current_version"])
        # Undo goes back to the chart: changing an analysis's settings keeps the chart it replaced.
        prev = row["prev_spec_json"] if old["op"]["type"] == "ml" and spec["op"]["type"] == "ml" else row["spec_json"]
        sets += ["spec_json = ?", "spec_hash = ?", "prev_spec_json = ?", "version_built = ?", "status = 'ready'", "error = NULL"]
        params += [json.dumps(spec), spec_hash(spec), prev, dataset["current_version"]]
        if spec["view"]["type"] != old["view"]["type"]:
            sets.append("point_json = NULL")  # the accent belongs to the old view's elements
    if title is not None:
        if not title.strip():
            raise ApiError(422, "invalid", "title: can't be empty")
        sets.append("title = ?")
        params.append(title.strip()[:200])
    env.db.execute(f"UPDATE widgets SET {', '.join(sets)} WHERE id = ?", (*params, row["id"]))  # noqa: S608
    if prepared is not None:
        from sherlock.ml import runner as ml

        ml.link(env.db, row["id"], ml.launch(env, dataset, prepared, "user", row["id"]))
    bump_state(env.db, dataset["id"])
    new = get_row(env.db, row["id"])
    _emit(env, dataset, new)
    if spec is not None:
        _stories(env, dataset, [row["id"]])
    return new


def undo(env: Env, dataset: sqlite3.Row, row: sqlite3.Row) -> sqlite3.Row:
    """Swap the spec with the one before the last change, so a second undo puts it back."""
    if not row["prev_spec_json"]:
        raise ApiError(409, "conflict", "This widget has no earlier version to go back to.")
    current, prev = json.loads(row["spec_json"]), json.loads(row["prev_spec_json"])
    title = row["title"]
    if current["op"]["type"] == "ml" and prev["op"]["type"] == "sql":
        title = (current["view"].get("options") or {}).get("chart_title") or title  # back to the chart's own title
    elif current["op"]["type"] == "sql" and prev["op"]["type"] == "ml":
        title = analysis_title(prev)
    env.db.execute(
        "UPDATE widgets SET spec_json = ?, spec_hash = ?, prev_spec_json = ?, point_json = NULL, status = 'ready', "
        "error = NULL, title = ?, updated_at = ? WHERE id = ?",
        (row["prev_spec_json"], spec_hash(prev), row["spec_json"], title, now_iso(), row["id"]),
    )
    run = env.db.execute("SELECT * FROM runs WHERE id = ?", (row["run_id"],)).fetchone() if row["run_id"] else None
    if run is not None and json.loads(row["prev_spec_json"])["op"]["type"] == "ml":
        from sherlock.ml import runner as ml

        ml.link(env.db, row["id"], run)  # back to the analysis: its status is its run's again
    bump_state(env.db, dataset["id"])
    new = get_row(env.db, row["id"])
    _emit(env, dataset, new)
    _stories(env, dataset, [row["id"]])  # its card tells the spec it has now
    return new


def delete(env: Env, dataset: sqlite3.Row, row: sqlite3.Row) -> None:
    """Soft delete (10 minutes, PRD DASH-9). The widget's story cards go with it and come back with it."""
    now = now_iso()
    env.db.execute("UPDATE widgets SET deleted_at = ?, updated_at = ? WHERE id = ?", (now, now, row["id"]))
    env.db.execute("UPDATE cards SET deleted_at = ? WHERE widget_id = ? AND deleted_at IS NULL", (now, row["id"]))
    bump_state(env.db, dataset["id"])
    _emit(env, dataset, get_row(env.db, row["id"]), deleted=True)
    _stories(env, dataset, [], "widget")  # the overview no longer counts it


def restore(env: Env, dataset: sqlite3.Row, row: sqlite3.Row) -> sqlite3.Row:
    if row["deleted_at"] is None:
        return row
    env.db.execute("UPDATE cards SET deleted_at = NULL WHERE widget_id = ? AND deleted_at = ?", (row["id"], row["deleted_at"]))
    env.db.execute("UPDATE widgets SET deleted_at = NULL, updated_at = ? WHERE id = ?", (now_iso(), row["id"]))
    bump_state(env.db, dataset["id"])
    new = get_row(env.db, row["id"])
    _emit(env, dataset, new)
    _stories(env, dataset, [], "widget")  # the overview counts it again
    return new


def data(env: Env, dataset: sqlite3.Row, row: sqlite3.Row, filters: list[dict], version: int | None = None) -> dict:
    """`WidgetData` (TRD §4.5) for a widget on a version (default current), through the cache."""
    version = version or dataset["current_version"]
    spec = json.loads(row["spec_json"])
    if spec["op"]["type"] == "ml":
        from sherlock.ml import runner as ml

        return ml.widget_data(env, dataset, row)  # an analysis ignores the dashboard's filter (its rows are its scope)
    sql = compiled(env, dataset, spec, version, filters)
    key = cache_key(row["spec_hash"], version, sql)
    hit = CACHE.get(env.db, dataset["id"], key)
    if hit is None:
        with connection(env, dataset, version) as conn:
            hit = run_query(conn, sql)
        CACHE.put(env.db, dataset["id"], key, hit)
    out = {"version": version, **hit}
    point = json.loads(row["point_json"]) if row["point_json"] else None
    if point:
        out["highlight"] = point
    return out


def explain(env: Env, dataset: sqlite3.Row, row: sqlite3.Row, filters: list[dict]) -> dict:
    """What "How do you know?" shows: the SQL exactly as it runs now (with the active filter)."""
    spec = json.loads(row["spec_json"])
    out = {"scope": spec["scope"], "params": {}, "version": dataset["current_version"], "op": spec["op"]["type"]}
    if spec["op"]["type"] == "sql":
        out["sql"] = compiled(env, dataset, spec, dataset["current_version"], filters)
    else:
        out["recipe"] = spec["op"]["recipe"]
        out["params"] = spec["op"].get("params", {})
        out["run_id"] = row["run_id"]
    return out
