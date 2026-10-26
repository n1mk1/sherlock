"""The ML runner (TRD §4.8, §7.5; PRD ML-8 – ML-10): run requests and their cache, the `ml_run` job,
a run's artifacts and fact sheet, and the reads behind the runs API.

- **Request → run.** A `RunRequest` is checked against the recipe's manifest, its target is filled in
  with the best guess when missing, and the minimum rows are enforced before anything is queued. The
  cache key is sha1(version, scope, recipe, method, params): the same request on the same version
  returns the stored run at once (a finished one, or the one still going).
- **The job.** `ml_run` loads the run's version, calls `analysis.analyze` (which reports the TRD
  progress labels) and writes `runs/<id>/`: `repro.py`, `model.joblib`, `model_card.json` and
  `results/` (`importance.json`, `partial_dependence.json`). The model card's numbers come from executing
  `repro.py`, so the exported notebook reports the same ones.
- **Widgets.** A widget with an ML op points at its run (`widgets.run_id`); its status follows the
  run's, and every `run.updated` is followed by `widget.updated` for the widgets showing that run.
- **Outdated.** `outdate` marks finished runs whose columns changed in a new version (the cascade,
  TRD §7.6); their widgets show "Outdated" with Re-run, or re-run by themselves.
"""

import hashlib
import json
import sqlite3
from dataclasses import dataclass

import duckdb
import joblib
import numpy as np
import pandas as pd
import sklearn
from pydantic import ValidationError

from sherlock.db.util import new_id, now_iso
from sherlock.errors import ApiError, not_found
from sherlock.jobs.events import EventBus, emit
from sherlock.jobs.runner import JobContext, insert_job, register
from sherlock.ml import core, registry
from sherlock.ml.plan import MIN_ROWS, SEED, make_plan
from sherlock.rows.query import ident
from sherlock.storage import dataset_dir
from sherlock.widgets import compile as wc
from sherlock.widgets import service as ws
from sherlock.widgets.spec import Scope

RUNNING = ("queued", "running")
FINISHED_OK = ("done", "outdated")
VIEWS = ("importance", "partial_dependence", "baselines", "confusion", "roc")
WIDGET_STATUS = {"queued": "building", "running": "building", "done": "ready", "outdated": "outdated",
                 "failed": "error", "cancelled": "error"}
PREVIEW_ROWS = 5000


@dataclass
class Prepared:
    """A checked request: the scope with its target filled in, and where it runs."""
    recipe: str
    method: str
    scope: dict
    params: dict
    version: int
    key: str
    rows_sql: str


# --- requests --------------------------------------------------------------------------------------

def parse_request(raw: dict) -> dict:
    """`RunRequest` (TRD §4.8) → `{recipe, method, scope, params, filters, widget_id}`, checked
    against the recipe's manifest; unknown or disabled recipes and methods are `422`."""
    if not isinstance(raw, dict):
        raise ApiError(422, "invalid", "Send a run request.")
    recipe = raw.get("recipe") or registry.DRIVER["id"]
    if recipe != registry.DRIVER["id"]:
        stub = next((s for s in registry.STUBS if s["id"] == recipe), None)
        if stub is None:
            raise ApiError(422, "invalid", f"There's no analysis called {recipe!r}.")
        raise ApiError(422, "invalid", f"{stub['label']} isn't available: {stub['reason'].lower()}.")
    method = raw.get("method") or "auto"
    if method not in [m["id"] for m in registry.DRIVER["methods"]]:
        raise ApiError(422, "invalid", "Only Auto is available in this release.")
    try:
        scope = Scope.model_validate(raw.get("scope") or {}).model_dump()
    except ValidationError as exc:
        err = exc.errors()[0]
        raise ApiError(422, "invalid", f"scope.{'.'.join(str(p) for p in err['loc'])}: {err['msg']}") from None
    filters = raw.get("filters") or []
    if not isinstance(filters, list):
        raise ApiError(422, "invalid", "filters: must be a list")
    widget_id = raw.get("widget_id")
    return {"recipe": recipe, "method": method, "scope": scope, "params": check_params(raw.get("params") or {}),
            "filters": filters, "widget_id": widget_id if isinstance(widget_id, str) else None}


def check_params(params: dict) -> dict:
    """The manifest's params with defaults filled in; integers outside their range are `422`."""
    if not isinstance(params, dict):
        raise ApiError(422, "invalid", "params: must be an object")
    out = {}
    for name, p in registry.DRIVER["params"]["properties"].items():
        value = params.get(name, p["default"])
        if not isinstance(value, int) or isinstance(value, bool) or not p["minimum"] <= value <= p["maximum"]:
            raise ApiError(422, "invalid", f"params.{name}: a whole number from {p['minimum']} to {p['maximum']}")
        out[name] = value
    return out


def cache_key(version: int, scope: dict, recipe: str, method: str, params: dict) -> str:
    raw = json.dumps([version, scope, recipe, method, params], sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode()).hexdigest()


def rows_sql(env: ws.Env, dataset: sqlite3.Row, scope: dict, version: int) -> str:
    """The run's rows as a WHERE clause: quarantine excluded, the scope's predicate and selection.
    ML runs never inherit the dashboard's filter; `filters` are folded into the predicate instead."""
    types = ws.user_types(env, dataset, version)
    rows = scope["rows"]
    predicate = wc.validate_predicate(rows["predicate"], list(types)) if rows.get("predicate") else None
    selection = ws.selection_sql(env.db, dataset["id"], rows["selection_id"]) if rows.get("selection_id") else None
    return wc.rows_clause(predicate, selection, None)


def datacard(env: ws.Env, dataset: sqlite3.Row, version: int) -> dict:
    from sherlock.profile import service as profile_service

    return profile_service.get_or_build(env.settings, env.db, env.cache, dataset, version)


def prepare(env: ws.Env, dataset: sqlite3.Row, req: dict) -> Prepared:
    """Fill in the target, fold `filters` into the predicate, enforce the minimum rows (PRD ML-10)."""
    version = dataset["current_version"]
    scope = json.loads(json.dumps(req["scope"]))
    types = ws.user_types(env, dataset, version)
    if req.get("filters"):
        folded = wc.filter_sql(wc.parse_filter({"and": req["filters"]}), types)
        if folded:
            old = scope["rows"].get("predicate")
            scope["rows"]["predicate"] = f"({old}) AND ({folded})" if old else folded
    scope["rows"]["inherit_global_filters"] = False
    card = datacard(env, dataset, version)
    targets = registry.targets(card)
    cols = scope["columns"]
    target = cols.get("target") or (targets[0] if targets else None)
    if target is None:
        raise ApiError(422, "invalid", "There's no column to explain: it needs a yes/no, a category or a number.")
    if target not in types:
        raise ApiError(422, "invalid", f"There's no column {target!r} to explain.")
    if target not in targets:
        raise ApiError(422, "invalid", f"{target} can't be explained: pick a yes/no, a category with up to 20 values, or a number.")
    cols["target"] = target
    if cols.get("features") is not None:
        unknown = [f for f in cols["features"] if f not in types]
        if unknown:
            raise ApiError(422, "invalid", f"There's no column {unknown[0]!r} to use.")
        cols["features"] = [f for f in cols["features"] if f != target]
    where = rows_sql(env, dataset, scope, version)
    with ws.connection(env, dataset, version) as conn:
        n = conn.execute(f"SELECT count(*) FROM t WHERE {where} AND {ident(target)} IS NOT NULL").fetchone()[0]  # noqa: S608
    if n < MIN_ROWS:
        raise ApiError(422, "invalid", f"This needs at least {MIN_ROWS} rows with {target} filled in; these rows have {n}.")
    key = cache_key(version, scope, req["recipe"], req["method"], req["params"])
    return Prepared(req["recipe"], req["method"], scope, req["params"], version, key, where)


def launch(env: ws.Env, dataset: sqlite3.Row, p: Prepared, created_by: str, widget_id: str | None = None) -> sqlite3.Row:
    """The cached run for this request, or a new one with its `ml_run` job queued."""
    db = env.db
    row = db.execute("SELECT * FROM runs WHERE dataset_id = ? AND cache_key = ?", (dataset["id"], p.key)).fetchone()
    if row is not None and row["status"] in ("done", *RUNNING):
        if widget_id and row["widget_id"] != widget_id:
            db.execute("UPDATE runs SET widget_id = ? WHERE id = ?", (widget_id, row["id"]))
        return get_run(db, row["id"])
    if row is None:
        run_id = new_id("run")
        db.execute(
            "INSERT INTO runs (id, dataset_id, widget_id, version, recipe, method, scope_json, params_json, cache_key, "
            "status, target, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)",
            (run_id, dataset["id"], widget_id, p.version, p.recipe, p.method, json.dumps(p.scope), json.dumps(p.params),
             p.key, p.scope["columns"]["target"], created_by, now_iso()),
        )
    else:  # a failed or cancelled run of the same request starts again under the same id
        run_id = row["id"]
        db.execute("UPDATE runs SET status = 'queued', error = NULL, model_card_json = NULL, finished_at = NULL, "
                   "widget_id = coalesce(?, widget_id) WHERE id = ?", (widget_id, run_id))
    job = insert_job(db, dataset["user_id"], dataset["id"], "ml_run", {"run_id": run_id})
    db.execute("UPDATE runs SET job_id = ? WHERE id = ?", (job["id"], run_id))
    ws.bump_state(db, dataset["id"])
    run = get_run(db, run_id)
    emit(db, env.bus, dataset["id"], dataset["user_id"], "run.updated", to_run(db, run))
    return run


def ml_spec(p: Prepared, view: str = "importance") -> dict:
    return {"scope": p.scope, "op": {"type": "ml", "recipe": p.recipe, "method": p.method, "params": p.params},
            "view": {"type": view}}


def request_from_spec(spec: dict) -> dict:
    op = spec["op"]
    return {"recipe": op["recipe"], "method": op.get("method") or "auto", "scope": spec["scope"],
            "params": check_params(op.get("params") or {}), "filters": []}


def link(db: sqlite3.Connection, widget_id: str, run: sqlite3.Row) -> None:
    """Point a widget at a run; its status follows the run's."""
    db.execute("UPDATE widgets SET run_id = ?, status = ?, error = ?, version_built = ?, updated_at = ? WHERE id = ?",
               (run["id"], WIDGET_STATUS[run["status"]], run["error"] if run["status"] in ("failed", "cancelled") else None,
                run["version"], now_iso(), widget_id))


# --- reads -----------------------------------------------------------------------------------------

def get_run(db: sqlite3.Connection, run_id: str) -> sqlite3.Row:
    row = db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise not_found("Run not found")
    return row


def to_run(db: sqlite3.Connection, row: sqlite3.Row, full: bool = False) -> dict:
    """`Run` (TRD §6.8). `summary` carries what a widget shows without the whole model card;
    `progress` is the job's while it runs. `full` adds the `model_card`."""
    card = json.loads(row["model_card_json"]) if row["model_card_json"] else None
    out = {
        "id": row["id"], "dataset_id": row["dataset_id"], "widget_id": row["widget_id"], "version": row["version"],
        "recipe": row["recipe"], "method": row["method"], "scope": json.loads(row["scope_json"]),
        "params": json.loads(row["params_json"]), "status": row["status"], "job_id": row["job_id"],
        "fact_sheet_id": row["fact_sheet_id"], "target": row["target"], "error": row["error"],
        "created_at": row["created_at"], "finished_at": row["finished_at"], "summary": None, "progress": None,
    }
    if card:
        best = max(card["baselines"], key=lambda b: b["value"])
        out["summary"] = {"verdict": card["verdict"], "verdict_text": card["verdict_text"], "metric": card["model"]["metric"],
                          "value": card["model"]["value"], "best_baseline": best, "chosen_model": card["chosen_model"],
                          "chosen_label": core.MODEL_LABELS.get(card["chosen_model"], card["chosen_model"]),
                          "rows": card["rows"]["train"], "excluded": len(card["excluded"]), "task": card["task"],
                          "misclassified": card.get("misclassified"), "views": result_views(card)}
    if row["status"] in RUNNING and row["job_id"]:
        job = db.execute("SELECT progress_json FROM jobs WHERE id = ?", (row["job_id"],)).fetchone()
        if job and job["progress_json"]:
            out["progress"] = json.loads(job["progress_json"])
    if full:
        out["model_card"] = card
    return out


def result_views(card: dict) -> list[str]:
    """The views a run can show: importance, then the confusion matrix and the ROC curve when it has them."""
    return ["importance"] + [v for v in ("confusion", "roc") if v in card]


def wrong_rows(db: sqlite3.Connection, settings, dataset: sqlite3.Row, row: sqlite3.Row) -> dict:
    """"Who did it get wrong?" (App Flow §9 step 5): a selection of the rows whose out-of-fold
    prediction missed, for the CSV tab's `?rows=`. Row ids are stable across versions."""
    _finished(row)
    path = run_folder(settings, dataset, row["id"]) / "results" / "oof.json"
    if not path.exists():
        raise ApiError(422, "invalid", "Only a run that explains categories has rows it got wrong.")
    oof = json.loads(path.read_text(encoding="utf-8"))
    ids = sorted({int(r["_row_id"]) for r in oof if r["actual"] != r["predicted"]})
    card = json.loads(row["model_card_json"])
    sel_id = new_id("sel")
    db.execute("INSERT INTO selections (id, dataset_id, version, predicate, row_ids_json, row_count, label, created_at) "
               "VALUES (?, ?, ?, NULL, ?, ?, ?, ?)",
               (sel_id, dataset["id"], dataset["current_version"], json.dumps(ids), len(ids),
                f"{card['target']}: predicted wrong", now_iso()))
    return {"selection_id": sel_id, "row_count": len(ids), "label": f"{card['target']}: predicted wrong"}


def run_folder(settings, dataset: sqlite3.Row, run_id: str):
    return dataset_dir(settings, dataset["user_id"], dataset["id"]) / "runs" / run_id


def _finished(row: sqlite3.Row) -> None:
    if row["status"] not in FINISHED_OK:
        raise ApiError(409, "conflict", "The analysis hasn't finished yet." if row["status"] in RUNNING
                       else f"The analysis {row['status']}: {row['error'] or 'no result'}.")


def results(settings, db: sqlite3.Connection, dataset: sqlite3.Row, row: sqlite3.Row, view: str,
            feature: str | None = None) -> dict:
    """`WidgetData` for one of a run's views (TRD §4.8)."""
    _finished(row)
    if view not in VIEWS:
        raise ApiError(422, "invalid", f"view: one of {', '.join(VIEWS)}")
    folder = run_folder(settings, dataset, row["id"])
    card = json.loads(row["model_card_json"])
    if view == "importance":
        table = json.loads((folder / "results" / "importance.json").read_text(encoding="utf-8"))
        columns = [{"name": "feature", "type": "VARCHAR"}, {"name": "importance", "type": "DOUBLE"}]
        rows = [[r["feature"], float(r["importance"])] for r in table]
    elif view in ("confusion", "roc"):
        if view not in card:
            raise ApiError(422, "invalid", "The confusion matrix is for categories" if view == "confusion"
                           else "The ROC curve is for a yes/no target (two values).")
        if view == "confusion":
            labels = card["confusion"]["labels"]
            columns = [{"name": "actual", "type": "VARCHAR"}, {"name": "predicted", "type": "VARCHAR"},
                       {"name": "n", "type": "BIGINT"}]
            rows = [[a, p, card["confusion"]["matrix"][i][j]] for i, a in enumerate(labels) for j, p in enumerate(labels)]
        else:
            columns = [{"name": "fpr", "type": "DOUBLE"}, {"name": "tpr", "type": "DOUBLE"}, {"name": "threshold", "type": "DOUBLE"}]
            rows = [[pt["fpr"], pt["tpr"], pt["threshold"]] for pt in card["roc"]["points"]]
    elif view == "baselines":
        columns = [{"name": "name", "type": "VARCHAR"}, {"name": "metric", "type": "VARCHAR"},
                   {"name": "value", "type": "DOUBLE"}, {"name": "ci_low", "type": "DOUBLE"}, {"name": "ci_high", "type": "DOUBLE"}]
        rows = [[b["name"], b["metric"], b["value"], None, None] for b in card["baselines"]]
        m = card["model"]
        rows.append([f"model: {core.MODEL_LABELS.get(card['chosen_model'], card['chosen_model'])}", m["metric"], m["value"],
                     m["ci"][0], m["ci"][1]])
    else:
        pdp = json.loads((folder / "results" / "partial_dependence.json").read_text(encoding="utf-8"))
        if feature is not None:
            match = next((p for p in pdp if p["feature"] == feature), None)
            if match is None:
                raise not_found(f"No partial dependence for {feature!r}; it covers the top {len(pdp)} factors.")
            columns = [{"name": "value", "type": "DOUBLE" if match["kind"] == "numeric" else "VARCHAR"},
                       {"name": "prediction", "type": "DOUBLE"}]
            rows = [[pt["value"], pt["prediction"]] for pt in match["points"]]
            return {"version": row["version"], "view": view, "feature": feature, "of": match["of"], "kind": match["kind"],
                    "columns": columns, "rows": rows, "row_count": len(rows), "truncated": False}
        columns = [{"name": "feature", "type": "VARCHAR"}, {"name": "value", "type": "VARCHAR"},
                   {"name": "prediction", "type": "DOUBLE"}]
        rows = [[p["feature"], str(pt["value"]), pt["prediction"]] for p in pdp for pt in p["points"]]
    return {"version": row["version"], "view": view, "columns": columns, "rows": rows, "row_count": len(rows),
            "truncated": False}


def widget_data(env: ws.Env, dataset: sqlite3.Row, widget: sqlite3.Row) -> dict:
    """An ML widget's `WidgetData`: its run's importance once it has one, plus the run itself (so the
    widget can show progress, the verdict line or "Outdated")."""
    run = env.db.execute("SELECT * FROM runs WHERE id = ?", (widget["run_id"],)).fetchone() if widget["run_id"] else None
    if run is not None and run["status"] in FINISHED_OK:
        out = results(env.settings, env.db, dataset, run, "importance")
    else:
        out = {"version": dataset["current_version"], "columns": [], "rows": [], "row_count": 0, "truncated": False}
    out["run"] = to_run(env.db, run) if run is not None else None
    return out


def preview(env: ws.Env, dataset: sqlite3.Row, req: dict) -> dict:
    """What the setup form shows before Run (TRD §4.8): the task, every column with its exclusion
    reason, the baselines for this scope, and an estimate."""
    p = prepare(env, dataset, req)
    card = datacard(env, dataset, p.version)
    target = p.scope["columns"]["target"]
    with ws.connection(env, dataset, p.version) as conn:
        data = conn.execute(f"SELECT * FROM t WHERE {p.rows_sql} ORDER BY _row_id").df()  # noqa: S608
    features = p.scope["columns"].get("features")
    plan = make_plan(data, card, p.rows_sql, target, features, features, p.params["cv_folds"])
    data = data[data[target].notna()]
    if len(data) > PREVIEW_ROWS:
        data = data.sample(n=PREVIEW_ROWS, random_state=SEED).sort_values("_row_id")
    X, y = core.prepare(data, target, plan.numeric, plan.categorical, plan.high_card)
    splits, _ = core.folds(X, y, plan.task, SEED, p.params["cv_folds"], core.group_labels(data, plan.group) if plan.group else None)
    base = core.baselines(X, y, plan.task, SEED, plan.numeric, plan.categorical, plan.high_card, splits)
    used = plan.rows["used"]
    estimate = int(min(p.params["time_budget_s"] + 20, max(3, round(used * len(plan.features) / 800))))
    columns = [c["name"] for c in card["columns"] if c["name"] != target]
    return {"target": target, "targets": registry.targets(card), "task": plan.task, "metric": plan.metric,
            "columns": columns, "features": plan.features, "excluded": plan.excluded, "forced": plan.forced,
            "rows": plan.rows, "sample": plan.sample, "baselines": base, "estimate_s": estimate,
            "scope": p.scope, "params": p.params, "cached": _cached(env.db, dataset["id"], p.key)}


def _cached(db: sqlite3.Connection, dataset_id: str, key: str) -> str | None:
    row = db.execute("SELECT id FROM runs WHERE dataset_id = ? AND cache_key = ? AND status = 'done'", (dataset_id, key)).fetchone()
    return row["id"] if row else None


def depends(row: sqlite3.Row, db: sqlite3.Connection | None = None) -> set[str]:
    """The columns a run read: its target, its features and the columns its row predicate names, and
    (given `db`) those its selection's predicate names (plan 2b.3)."""
    import sqlglot
    from sqlglot import exp

    cols = {row["target"]} | set(json.loads(row["features_json"] or "[]"))
    rows = json.loads(row["scope_json"])["rows"]
    conditions = [rows.get("predicate")]
    if db is not None and rows.get("selection_id"):
        try:
            conditions.append(ws.selection_sql(db, row["dataset_id"], rows["selection_id"]))
        except ApiError:  # the selection is gone; its rows were fixed when the run started
            pass
    for condition in filter(None, conditions):
        try:
            cols |= {c.name for c in sqlglot.parse_one(f"SELECT 1 FROM t WHERE {condition}", read="duckdb").find_all(exp.Column)}
        except sqlglot.errors.ParseError:
            pass
    return {c for c in cols if c and c not in ("_row_id", "_quarantine_reason")}


# --- the job ---------------------------------------------------------------------------------------

def facts_for(run_id: str, card: dict) -> dict:
    """The run's fact sheet (TRD §6.4): what a story card may say about it, each fact from the model
    card (whose numbers came from executing `repro.py`)."""
    from sherlock.stories.facts import fact

    m = card["model"]
    pct = m["metric"] != "r2"
    name = {"accuracy": "accuracy", "macro_f1": "macro F1", "r2": "R²"}[m["metric"]]
    prov = {"run_id": run_id, "formula": f"held-out {name}, {card['split']['folds']}-fold cross-validation"}
    best = max(card["baselines"], key=lambda b: b["value"])
    facts = {
        "model_score": fact(m["value"], "pct" if pct else "num", f"the model's {name} on held-out rows", **prov),
        "best_baseline": fact(best["value"], "pct" if pct else "num", f"{name} of the best simple rule ({best['name']})", **prov),
        "lift": fact(round(m["lift_over_best_baseline"] * (100 if pct else 1), 2), "num",
                     "points better than the best simple rule" if pct else "R² above the best simple rule", **prov),
        "rows": fact(card["rows"]["train"], "int", "rows used", **prov),
        "verdict": fact(card["verdict_text"], "text", "the verdict against the baselines", **prov),
    }
    if "auc" in m:
        facts["auc"] = fact(m["auc"], "num", "AUC on held-out rows", **prov)
    for i, imp in enumerate([r for r in card["importance"] if r["value"] > 0][:3], 1):
        facts[f"driver_{i}"] = fact(imp["column"], "text", f"factor number {i} by permutation importance", **prov)
        facts[f"driver_{i}_importance"] = fact(imp["value"], "num", f"relative importance of {imp['column']} (1 is the strongest)", **prov)
    return facts


ROC_POINTS = 50


def classification_checks(oof: pd.DataFrame) -> dict:
    """From the out-of-fold predictions: the confusion matrix (actual × predicted), how many rows were
    misclassified, and for two classes the ROC curve (at most 50 points) on the second class."""
    from sklearn.metrics import roc_auc_score, roc_curve

    labels = sorted(set(oof["actual"]) | set(oof["predicted"]))
    counts = pd.crosstab(oof["actual"], oof["predicted"]).reindex(index=labels, columns=labels, fill_value=0)
    out = {"confusion": {"labels": labels, "matrix": counts.values.astype(int).tolist()},
           "misclassified": int((oof["actual"] != oof["predicted"]).sum())}
    if "probability" in oof.columns and len(labels) == 2:
        positive = (oof["actual"] == labels[1]).astype(int)
        fpr, tpr, thr = roc_curve(positive, oof["probability"])
        keep = np.unique(np.linspace(0, len(fpr) - 1, min(ROC_POINTS, len(fpr))).round().astype(int))
        out["roc"] = {"positive": labels[1], "auc": round(float(roc_auc_score(positive, oof["probability"])), 6),
                      "points": [{"fpr": round(float(fpr[i]), 6), "tpr": round(float(tpr[i]), 6),
                                  "threshold": round(float(min(thr[i], 1.0)), 6)} for i in keep]}
    return out


def _emit_run(db: sqlite3.Connection, bus: EventBus | None, dataset: sqlite3.Row, run_id: str, job_id: str | None = None) -> None:
    """`run.updated`, then `widget.updated` for every live widget showing the run, with its status."""
    run = get_run(db, run_id)
    emit(db, bus, dataset["id"], dataset["user_id"], "run.updated", to_run(db, run), job_id=job_id)
    for w in db.execute("SELECT * FROM widgets WHERE run_id = ? AND deleted_at IS NULL", (run_id,)).fetchall():
        link(db, w["id"], run)
        emit(db, bus, dataset["id"], dataset["user_id"], "widget.updated", ws.to_widget(ws.get_row(db, w["id"])), job_id=job_id)


def _execute(ctx: JobContext) -> dict:
    from sherlock.ml.analysis import analyze

    run = get_run(ctx.db, ctx.params["run_id"])
    if run["status"] not in RUNNING:
        return {"skipped": f"run is {run['status']}"}
    dataset = ctx.db.execute("SELECT * FROM datasets WHERE id = ?", (run["dataset_id"],)).fetchone()
    if dataset is None or dataset["deleted_at"]:
        return {"skipped": "dataset deleted"}
    ctx.db.execute("UPDATE runs SET status = 'running' WHERE id = ?", (run["id"],))
    _emit_run(ctx.db, ctx.bus, dataset, run["id"], ctx.id)

    env = ws.Env(ctx.settings, ctx.db, ctx.cache, ctx.bus)
    scope, params, version = json.loads(run["scope_json"]), json.loads(run["params_json"]), run["version"]
    try:
        where = rows_sql(env, dataset, scope, version)
        with ws.connection(env, dataset, version) as conn:
            df = conn.execute("SELECT * FROM t ORDER BY _row_id").df()
        card = datacard(env, dataset, version)
        features = scope["columns"].get("features")
        a = analyze(df, card, where, scope["columns"]["target"], features=features, forced=features,
                    n_folds=params["cv_folds"], time_budget_s=params["time_budget_s"], run_id=run["id"], version=version,
                    progress=ctx.progress, check_cancel=ctx.check_cancel)
    except ApiError as exc:
        raise RuntimeError(exc.message) from None

    folder = run_folder(ctx.settings, dataset, run["id"])
    (folder / "results").mkdir(parents=True, exist_ok=True)
    (folder / "repro.py").write_text(a.code, encoding="utf-8")
    joblib.dump(a.final, folder / "model.joblib")
    (folder / "results" / "importance.json").write_text(
        a.result["importance"].to_json(orient="records", double_precision=6), encoding="utf-8")
    (folder / "results" / "partial_dependence.json").write_text(json.dumps(a.pdp, default=_plain), encoding="utf-8")
    checks = {}
    if "oof" in a.result:  # classification: who it got wrong, the confusion matrix and the ROC curve
        oof = a.result["oof"]
        (folder / "results" / "oof.json").write_text(oof.to_json(orient="records", double_precision=6), encoding="utf-8")
        checks = classification_checks(oof)
    libraries = {"pandas": pd.__version__, "numpy": np.__version__, "duckdb": duckdb.__version__,
                 "scikit-learn": sklearn.__version__}
    facts = facts_for(run["id"], a.card)
    sheet_id = new_id("fs")
    deps = sorted({a.plan.target, *a.plan.features})
    ctx.db.execute(
        "INSERT INTO fact_sheets (id, dataset_id, widget_id, run_id, version, facts_json, depends_columns_json, material_hash, "
        "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, '', ?)",
        (sheet_id, dataset["id"], run["widget_id"], run["id"], version, json.dumps(facts, default=_plain), json.dumps(deps), now_iso()),
    )
    model_card = {"run_id": run["id"], **a.card, **checks, "version": version, "scope": scope, "params": params,
                  "artifact_path": f"runs/{run['id']}/model.joblib", "fact_sheet_id": sheet_id,
                  "repro": {"libraries": libraries, "code_path": f"runs/{run['id']}/repro.py"}}
    (folder / "model_card.json").write_text(json.dumps(model_card, default=_plain, indent=1), encoding="utf-8")
    ctx.db.execute(
        "UPDATE runs SET status = 'done', model_card_json = ?, fact_sheet_id = ?, features_json = ?, artifact_dir = ?, "
        "repro_path = ?, sample_json = ?, libraries_json = ?, error = NULL, finished_at = ? WHERE id = ?",
        (json.dumps(model_card, default=_plain), sheet_id, json.dumps(a.plan.features), f"runs/{run['id']}/",
         f"runs/{run['id']}/repro.py", json.dumps(a.plan.sample) if a.plan.sample else None, json.dumps(libraries),
         now_iso(), run["id"]),
    )
    ws.bump_state(ctx.db, dataset["id"])
    _emit_run(ctx.db, ctx.bus, dataset, run["id"], ctx.id)
    if _settle(env, run["id"], ctx.id):
        ctx.runner.wake()
        return {"run_id": run["id"], "outdated": True}
    widget_ids = [w["id"] for w in ctx.db.execute("SELECT id FROM widgets WHERE run_id = ? AND deleted_at IS NULL", (run["id"],))]
    if widget_ids:
        ws._stories(env, dataset, widget_ids)  # the widget's story card tells the result (App Flow §9 step 4)
        ctx.runner.wake()
    return {"run_id": run["id"], "verdict": a.card["verdict"], "model": a.model, "metric": a.card["model"]["metric"],
            "value": a.card["model"]["value"]}


def _plain(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return str(v)


async def run(ctx: JobContext) -> dict:
    import asyncio

    return await asyncio.to_thread(_execute, ctx)


def on_failure(db: sqlite3.Connection, bus: EventBus | None, job: sqlite3.Row, message: str) -> None:
    run_id = json.loads(job["params_json"]).get("run_id")
    row = db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone() if run_id else None
    if row is None or row["status"] not in RUNNING:
        return
    status = "cancelled" if job["status"] == "cancelled" else "failed"
    db.execute("UPDATE runs SET status = ?, error = ?, finished_at = ? WHERE id = ?",
               (status, "Cancelled." if status == "cancelled" else message, now_iso(), run_id))
    dataset = db.execute("SELECT * FROM datasets WHERE id = ?", (row["dataset_id"],)).fetchone()
    if dataset is not None:
        _emit_run(db, bus, dataset, run_id, job["id"])
        from sherlock.stories import service as stories

        # Its widgets' cards tell an earlier run, or nothing: outdated, not ready or spinning (plan 1.2).
        for w in db.execute("SELECT id FROM widgets WHERE run_id = ? AND deleted_at IS NULL", (run_id,)).fetchall():
            stories.mark_widget_card(db, bus, dataset, w["id"], "outdated", job["id"])


register("ml_run", run, on_failure)


# --- outdated (the cascade, TRD §7.6) --------------------------------------------------------------

def outdate(db: sqlite3.Connection, bus: EventBus | None, dataset: sqlite3.Row, changes_since,
            job_id: str | None = None) -> list[str]:
    """Mark finished runs of earlier versions whose columns changed since their version as outdated
    (PRD ML-9); returns their ids. `changes_since(version)` is `(changed columns, everything)` up to
    the current version. Runs that read none of the changed columns still hold for the new version."""
    out = []
    for r in db.execute("SELECT * FROM runs WHERE dataset_id = ? AND status = 'done' AND version < ?",
                        (dataset["id"], dataset["current_version"])).fetchall():
        changed, everything = changes_since(r["version"])
        if everything or depends(r, db) & changed:
            db.execute("UPDATE runs SET status = 'outdated' WHERE id = ?", (r["id"],))
            out.append(r["id"])
    for run_id in out:
        _emit_run(db, bus, dataset, run_id, job_id)
    if out:
        ws.bump_state(db, dataset["id"])
    return out


def ask_first(db: sqlite3.Connection, dataset: sqlite3.Row) -> bool:
    """The user's "Story updates: Ask first" (PRD ML-9): outdated analyses wait for Re-run."""
    from sherlock.db import users
    from sherlock.routers.me import effective_settings

    user = users.get(db, dataset["user_id"])
    return effective_settings(user.settings if user else {}).story_updates == "ask"


def _settle(env: ws.Env, run_id: str, job_id: str | None) -> bool:
    """A run that finished after the data changed (cascades skip runs still going) is checked like the
    cascade would: outdated when its columns changed since its version, and re-run for its widgets
    unless the user asked first. True when it went outdated."""
    from sherlock.jobs.cascade import changes

    dataset = env.db.execute("SELECT * FROM datasets WHERE id = ?", (get_run(env.db, run_id)["dataset_id"],)).fetchone()
    current = dataset["current_version"]
    if get_run(env.db, run_id)["version"] >= current:
        return False
    stale = outdate(env.db, env.bus, dataset, lambda v: changes(env.db, dataset["id"], v, current), job_id)
    if run_id not in stale:
        return False
    if not ask_first(env.db, dataset):
        for w in env.db.execute("SELECT * FROM widgets WHERE run_id = ? AND deleted_at IS NULL", (run_id,)).fetchall():
            try:
                rerun_widget(env, dataset, w)
            except ApiError as exc:
                env.db.execute("UPDATE widgets SET status = 'error', error = ? WHERE id = ?", (exc.message, w["id"]))
            emit(env.db, env.bus, dataset["id"], dataset["user_id"], "widget.updated", ws.to_widget(ws.get_row(env.db, w["id"])),
                 job_id=job_id)
    return True


def rerun_widget(env: ws.Env, dataset: sqlite3.Row, widget: sqlite3.Row, created_by: str = "user") -> sqlite3.Row:
    """Run a widget's analysis again on the current version (Re-run, or automatic per the
    story-update setting)."""
    spec = json.loads(widget["spec_json"])
    p = prepare(env, dataset, request_from_spec(spec))
    run = launch(env, dataset, p, created_by, widget["id"])
    link(env.db, widget["id"], run)
    if run["status"] in RUNNING:  # its card says so until the run's story is told (or the run fails)
        from sherlock.stories import service as stories

        stories.mark_widget_card(env.db, env.bus, dataset, widget["id"], "updating")
    return run
