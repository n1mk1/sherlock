"""A driver analysis from data to model card (TRD §7.5, §6.6; PRD ML-3, ML-5), without the database:
the runner (`ml/runner.py`) feeds it the version's DataFrame and stores what it returns, and the
planted-truth tests call it directly.

Auto tries a linear model, gradient boosting and a random forest with the same folds and keeps the
best by the task's metric. The winner's numbers in the model card come from executing the run's
reproduction code, so the exported notebook reports the same ones.
"""

import time
from dataclasses import dataclass

import duckdb
import numpy as np
import pandas as pd

from sherlock.ml import core, repro
from sherlock.ml.plan import Plan, make_plan

PD_TOP = 5
PD_POINTS = 10
LIFT = {"accuracy": 0.02, "macro_f1": 0.02, "r2": 0.05}  # beats the baseline by at least this much


@dataclass
class Analysis:
    plan: Plan
    model: str
    alternatives: list[dict]
    code: str
    result: dict            # what reproduce() returned
    card: dict              # the ModelCard (TRD §6.6) without run-specific ids
    pdp: list[dict]         # partial dependence for the top features
    final: object           # the winner fitted on all rows


def scope_frame(df: pd.DataFrame, rows_sql: str) -> pd.DataFrame:
    """The run's rows, selected exactly as `reproduce` selects them."""
    t = df  # noqa: F841 - DuckDB reads the local DataFrame `t`
    return duckdb.sql(f"SELECT * FROM t WHERE {rows_sql} ORDER BY _row_id").df()


def analyze(df: pd.DataFrame, card: dict, rows_sql: str, target: str, *, features: list[str] | None = None,
            forced: list[str] | None = None, n_folds: int = core.FOLDS, time_budget_s: float = 60,
            run_id: str = "run", version: int = 0, progress=lambda *_: None, check_cancel=lambda: None) -> Analysis:
    progress(1, 6, "preparing data")
    data = scope_frame(df, rows_sql)
    progress(2, 6, "checking for leakage")
    plan = make_plan(data, card, rows_sql, target, features, forced)
    data = data[data[target].notna()]
    if plan.sample:
        data = data.sample(n=plan.sample["n"], random_state=core_seed()).sort_values("_row_id")
    X, y = core.prepare(data, plan.target, plan.numeric, plan.categorical, plan.high_card)
    splits = core.folds(X, y, plan.task, core_seed(), n_folds)
    check_cancel()

    progress(3, 6, "setting baselines")
    progress(4, 6, "testing models")
    started = time.monotonic()
    tried = []
    for name in core.MODELS[plan.task]:
        check_cancel()
        if tried and time.monotonic() - started > time_budget_s:
            break  # the time budget: keep what has been tried
        r = core.evaluate(name, X, y, plan.task, core_seed(), plan.numeric, plan.categorical, plan.high_card, splits)
        tried.append({"model": name, "metric": r["metric"], "mean": r["mean"]})
    best = max(tried, key=lambda t: t["mean"])
    alternatives = [t for t in tried if t is not best]

    progress(5, 6, "explaining")
    code = repro.render(plan, best["model"], alternatives, run_id, version, n_folds)
    result = repro.execute(code, df)
    final = core.pipeline(best["model"], plan.numeric, plan.categorical, plan.high_card, plan.task, core_seed())
    final.fit(X, y)
    imp = result["importance"]
    pdp = partial_dependence(final, X, y, plan, list(imp["feature"][:PD_TOP]))

    progress(6, 6, "writing the model card")
    return Analysis(plan, best["model"], alternatives, code, result, model_card(plan, best["model"], alternatives, result, y), pdp, final)


def core_seed() -> int:
    return 42


def partial_dependence(model, X: pd.DataFrame, y: pd.Series, plan: Plan, features: list[str]) -> list[dict]:
    """For each feature: the average prediction with every row set to each of a few values (quantiles
    for numbers, the most common values for categories); probabilities of the positive class for a
    two-class target."""
    out = []
    binary = plan.task == "classification" and y.nunique() == 2
    positive = sorted(y.unique().tolist(), key=str)[-1] if binary else None
    for f in features:
        if f in plan.numeric:
            values = sorted(set(np.nanquantile(X[f].astype(float), np.linspace(0.05, 0.95, PD_POINTS)).round(4).tolist()))
        else:
            values = X[f].value_counts().index[:PD_POINTS].tolist()
        points = []
        for v in values:
            Xv = X.copy()
            Xv[f] = v
            if binary:
                classes = list(model.classes_)
                pred = float(model.predict_proba(Xv)[:, classes.index(positive)].mean())
            elif plan.task == "regression":
                pred = float(np.mean(model.predict(Xv)))
            else:
                pred = float((model.predict(Xv) == y.mode()[0]).mean())
            points.append({"value": v if not isinstance(v, (np.floating, np.integer)) else v.item(), "prediction": round(pred, 6)})
        out.append({"feature": f, "kind": "numeric" if f in plan.numeric else "categorical", "points": points,
                    "of": f"probability of {plan.target} = {positive}" if binary else f"predicted {plan.target}"})
    return out


def verdict(metric: str, value: float, baselines: list[dict]) -> tuple[str, str]:
    """Against the best baseline. When a single column does as well as the model, the text names it:
    the signal is real but one column carries it."""
    best = max(baselines, key=lambda b: b["value"])
    lift = value - best["value"]
    unit = "points" if metric != "r2" else "R²"
    shown = f"{lift * 100:.1f} points" if metric != "r2" else f"{lift:.2f} in R²"
    if lift >= LIFT[metric]:
        return "beats_baseline", f"Beats the best simple rule by {shown}."
    if lift > 0:
        return "weak", f"Only {shown} better than the best simple rule: treat these drivers as weak."
    floor = min(b["value"] for b in baselines)
    if best.get("column") and best["value"] - floor >= LIFT[metric]:
        score = f"{best['value'] * 100:.1f}%" if metric != "r2" else f"R² {best['value']:.2f}"
        return "no_signal", (f"No better than {best['column']} alone ({score}): the other columns add nothing on held-out rows.")
    return "no_signal", f"No signal: the model does no better than the best simple rule ({unit} compared on held-out rows)."


def model_card(plan: Plan, model: str, alternatives: list[dict], result: dict, y: pd.Series) -> dict:
    m = result["metrics"]
    best_base = max(b["value"] for b in result["baselines"])
    v, text = verdict(m["metric"], m["value"], result["baselines"])
    warnings = []
    if plan.task == "classification":
        share = float(y.value_counts(normalize=True).iloc[0])
        if share > 0.7:
            warnings.append({"code": "class_imbalance", "text": f"{share:.0%} of rows share one outcome.",
                             "suggestion": "Compare against the baseline, not against 50%."})
    if plan.rows["with_target"] < 300:
        warnings.append({"code": "small_sample", "text": f"Only {plan.rows['with_target']} rows have {plan.target}; intervals are wide.",
                         "suggestion": "Read the interval, not only the score."})
    for f in plan.forced:
        warnings.append({"code": "forced_in", "text": f"{f['column']} is used although the checks left it out: {f['reason']}.",
                         "suggestion": "Keep it only if it's known before the outcome."})
    if plan.high_card:
        warnings.append({"code": "high_cardinality", "text": f"{', '.join(plan.high_card)} have many values and were target-encoded inside the folds.",
                         "suggestion": "Their importance can be inflated; check them by hand."})
    model_block = {"metric": m["metric"], "value": m["value"], "ci": m["ci"], "folds": m["folds"],
                   "lift_over_best_baseline": round(m["value"] - best_base, 6)}
    for k in ("auc", "mae"):
        if k in m:
            model_block[k] = m[k]
    return {
        "recipe": "driver_analysis", "method": "auto", "chosen_model": model, "task": plan.task, "target": plan.target,
        "features_used": plan.features, "excluded": plan.excluded,
        "rows": {**plan.rows, "train": result["rows"]},
        "split": {"kind": "stratified_kfold" if plan.task == "classification" else "kfold", "folds": len(m["folds"]), "seed": core_seed()},
        "baselines": result["baselines"], "model": model_block,
        "alternatives": [{"model": a["model"], "label": core.MODEL_LABELS.get(a["model"], a["model"]), "metric": a["metric"],
                          "value": round(a["mean"], 6)} for a in alternatives],
        "verdict": v, "verdict_text": text,
        "importance": [{"column": r.feature, "value": float(r.importance)} for r in result["importance"].itertuples()],
        "warnings": warnings,
        "limits": [f"{result['rows']:,} rows" + ("; intervals are wide" if result["rows"] < 1000 else ""), "correlational, not causal"],
        "sample": plan.sample,
    }
