"""The model code of a driver analysis (TRD §7.5 steps 4–8), written to be self-contained.

The app's runner calls these functions, and each run's `repro.py` carries their source verbatim
(`sherlock/ml/repro.py`), so the exported notebook trains, scores and explains the model with the
same code, the same folds and the same seed: its metrics match the model card. Only pandas, numpy
and scikit-learn are used here.
"""

import warnings

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier, DummyRegressor
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import accuracy_score, f1_score, mean_absolute_error, r2_score, roc_auc_score
from sklearn.model_selection import KFold, StratifiedKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler, TargetEncoder
from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor

FOLDS = 5
MODELS = {
    "classification": ["logistic_regression", "gradient_boosting", "random_forest"],
    "regression": ["ridge", "gradient_boosting", "random_forest"],
}
MODEL_LABELS = {"logistic_regression": "Logistic regression", "ridge": "Ridge regression",
                "gradient_boosting": "Gradient boosting", "random_forest": "Random forest"}


def prepare(data, target, numeric, categorical, high_card):
    """X and y: numbers as floats (missing stays missing), categories as text with "(missing)"."""
    X = pd.DataFrame(index=data.index)
    for c in numeric:
        X[c] = pd.to_numeric(data[c], errors="coerce").astype(float)
    for c in categorical + high_card:
        X[c] = data[c].astype(str).where(data[c].notna(), "(missing)")
    y = data[target]
    if y.dtype == object or str(y.dtype) == "bool":
        y = y.astype(str)
    return X, y.reset_index(drop=True).set_axis(X.index)


def preprocessor(numeric, categorical, high_card, task, seed):
    """Imputation, scaling and encoding, fitted inside each fold (TRD §7.5 step 5)."""
    parts = []
    if numeric:
        parts.append(("numeric", Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())]), numeric))
    if categorical:
        parts.append(("categorical", OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=10,
                                                   sparse_output=False), categorical))
    if high_card:
        parts.append(("high_cardinality", TargetEncoder(target_type="continuous" if task == "regression" else "auto",
                                                        random_state=seed), high_card))
    return ColumnTransformer(parts, remainder="drop")


def make_model(name, task, seed):
    if task == "classification":
        return {"logistic_regression": LogisticRegression(C=1.0, max_iter=2000),
                "gradient_boosting": HistGradientBoostingClassifier(random_state=seed),
                "random_forest": RandomForestClassifier(n_estimators=200, random_state=seed, n_jobs=1),
                "majority": DummyClassifier(strategy="most_frequent"),
                "one_column_rule": DecisionTreeClassifier(max_depth=1, random_state=seed)}[name]
    return {"ridge": Ridge(alpha=1.0),
            "gradient_boosting": HistGradientBoostingRegressor(random_state=seed),
            "random_forest": RandomForestRegressor(n_estimators=200, random_state=seed, n_jobs=1),
            "majority": DummyRegressor(strategy="mean"),
            "one_column_rule": DecisionTreeRegressor(max_depth=1, random_state=seed)}[name]


def folds(X, y, task, seed, n_folds=FOLDS):
    split = (StratifiedKFold(n_folds, shuffle=True, random_state=seed) if task == "classification"
             else KFold(n_folds, shuffle=True, random_state=seed))
    return list(split.split(X, y))


def metric_name(task, y):
    if task == "regression":
        return "r2"
    return "accuracy" if y.nunique() == 2 else "macro_f1"


def score(metric, y_true, y_pred):
    if metric == "accuracy":
        return float(accuracy_score(y_true, y_pred))
    if metric == "macro_f1":
        return float(f1_score(y_true, y_pred, average="macro"))
    return float(r2_score(y_true, y_pred))


def pipeline(name, numeric, categorical, high_card, task, seed):
    return Pipeline([("prepare", preprocessor(numeric, categorical, high_card, task, seed)),
                     ("model", make_model(name, task, seed))])


def evaluate(name, X, y, task, seed, numeric, categorical, high_card, splits=None):
    """Cross-validated scores of one model: {metric, folds, mean, auc?, mae?} plus the fitted
    per-fold pipelines (for importance)."""
    warnings.filterwarnings("ignore", message="Unknown solver options")  # scikit-learn 1.5 with a newer SciPy
    metric = metric_name(task, y)
    splits = splits or folds(X, y, task, seed)
    out = {"metric": metric, "folds": [], "fitted": []}
    aucs, maes = [], []
    for train, test in splits:
        p = pipeline(name, numeric, categorical, high_card, task, seed)
        p.fit(X.iloc[train], y.iloc[train])
        pred = p.predict(X.iloc[test])
        out["folds"].append(score(metric, y.iloc[test], pred))
        out["fitted"].append((p, test))
        if metric == "accuracy" and hasattr(p, "predict_proba") and name != "majority":
            proba = p.predict_proba(X.iloc[test])[:, 1]
            aucs.append(float(roc_auc_score(y.iloc[test], proba)))
        if task == "regression":
            maes.append(float(mean_absolute_error(y.iloc[test], pred)))
    out["mean"] = float(np.mean(out["folds"]))
    if aucs:
        out["auc"] = float(np.mean(aucs))
    if maes:
        out["mae"] = float(np.mean(maes))
    return out


def baselines(X, y, task, seed, numeric, categorical, high_card, splits):
    """The majority (or mean) and the best one-column rule (a depth-one tree on each column)."""
    first = evaluate("majority", X, y, task, seed, numeric, categorical, high_card, splits)
    label = "everyone gets the most common outcome" if task == "classification" else "predict the average"
    rows = [{"name": label, "metric": first["metric"], "value": first["mean"]}]
    best = None
    for col in numeric + categorical + high_card:
        one = evaluate("one_column_rule", X[[col]], y, task, seed,
                       [col] if col in numeric else [], [col] if col in categorical else [],
                       [col] if col in high_card else [], splits)
        if best is None or one["mean"] > best[1]:
            best = (col, one["mean"])
    if best is not None:
        rows.append({"name": f"best one-column rule: {best[0]}", "metric": first["metric"], "value": best[1], "column": best[0]})
    return rows


def importance(fitted, X, y, metric, seed):
    """Permutation importance on each held-out fold (10 repeats), averaged; 1.0 is the strongest."""
    scoring = {"accuracy": "accuracy", "macro_f1": "f1_macro", "r2": "r2"}[metric]
    total = pd.Series(0.0, index=X.columns)
    for p, test in fitted:
        r = permutation_importance(p, X.iloc[test], y.iloc[test], n_repeats=10, random_state=seed, scoring=scoring)
        total += pd.Series(r.importances_mean, index=X.columns)
    raw = (total / len(fitted)).clip(lower=0)
    top = raw.max()
    table = pd.DataFrame({"feature": raw.index, "importance": (raw / top if top > 0 else raw).round(4), "raw": raw.round(6)})
    return table.sort_values(["importance", "feature"], ascending=[False, True]).reset_index(drop=True)


def run(data, target, numeric, categorical, high_card, task, model, seed=42, n_folds=FOLDS):
    """Train and score `model` the way Sherlock did: the same folds, baselines and importance."""
    X, y = prepare(data, target, numeric, categorical, high_card)
    splits = folds(X, y, task, seed, n_folds)
    result = evaluate(model, X, y, task, seed, numeric, categorical, high_card, splits)
    base = baselines(X, y, task, seed, numeric, categorical, high_card, splits)
    imp = importance(result["fitted"], X, y, result["metric"], seed)
    sd = float(np.std(result["folds"], ddof=1)) if len(result["folds"]) > 1 else 0.0
    half = float(1.96 * sd / np.sqrt(len(result["folds"])))
    metrics = {"metric": result["metric"], "value": round(result["mean"], 6),
               "ci": [round(result["mean"] - half, 6), round(result["mean"] + half, 6)],
               "folds": [round(f, 6) for f in result["folds"]]}
    for k in ("auc", "mae"):
        if k in result:
            metrics[k] = round(result[k], 6)
    out = {"metrics": metrics, "baselines": base, "importance": imp, "rows": int(len(X))}
    if task == "classification":
        out["oof"] = out_of_fold(result["fitted"], X, y, data)
    return out


def out_of_fold(fitted, X, y, data):
    """Each row's prediction from the fold that held it out: `_row_id`, actual, predicted and, for
    two classes, the probability of the second class (sorted order)."""
    frames = []
    for p, test in fitted:
        part = pd.DataFrame({"actual": y.iloc[test].astype(str).values,
                             "predicted": pd.Series(p.predict(X.iloc[test])).astype(str).values}, index=X.index[test])
        if y.nunique() == 2:
            part["probability"] = p.predict_proba(X.iloc[test])[:, 1]
        frames.append(part)
    oof = pd.concat(frames).sort_index()
    if "_row_id" in data.columns:
        oof.insert(0, "_row_id", data.loc[oof.index, "_row_id"].astype(int).values)
    return oof.reset_index(drop=True)
