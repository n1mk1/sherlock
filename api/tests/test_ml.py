"""ML (TRD §7.5, §4.8, §14; PRD ML-1 – ML-10): planted truth through the analysis, then the runs API
end to end on a planted file: recipes with reasons, the setup preview, a run with its model card,
results, reproduction code and cache, the builder's driver widget, and runs marked outdated by the
cascade."""

import time

import numpy as np
import pandas as pd
import pytest

from sherlock.errors import ApiError
from sherlock.eval import planted
from sherlock.ml import repro
from sherlock.ml.analysis import analyze
from sherlock.ml.plan import make_plan
from tests.test_jobs import wait_for, wait_status

API = "/api/v1"
ALL = "_quarantine_reason IS NULL AND (1=1)"


def _analyze(df: pd.DataFrame, target: str, leakage: dict | None = None, **kw):
    return analyze(planted.as_version(df), planted.card_for(df, target, leakage), ALL, target, **kw)


# --- planted truth (PRD ML-3) ----------------------------------------------------------------------

def test_drivers_are_found_and_the_leak_and_the_id_are_left_out():
    a = _analyze(planted.drivers(), "outcome")
    order = [i["column"] for i in a.card["importance"]]
    assert order[:2] == ["strong", "moderate"], order
    assert order.index("noise") > order.index("group")
    excluded = {e["column"]: e["reason"] for e in a.card["excluded"]}
    assert "leak" in excluded and "leakage" in excluded["leak"]
    assert "code" in excluded and "ID" in excluded["code"]
    assert a.card["verdict"] == "beats_baseline"
    assert a.card["model"]["value"] > max(b["value"] for b in a.card["baselines"])
    assert {b["name"].split(":")[0] for b in a.card["baselines"]} == {"everyone gets the most common outcome", "best one-column rule"}
    assert a.card["split"] == {"kind": "stratified_kfold", "folds": 5, "seed": 42}


def test_pure_noise_is_reported_as_no_signal():
    a = _analyze(planted.noise(), "outcome")
    assert a.card["verdict"] == "no_signal", a.card["verdict_text"]
    assert a.card["verdict_text"].startswith("No signal")


def test_a_regression_target_is_explained():
    a = _analyze(planted.regression(), "value")
    assert a.plan.task == "regression" and a.card["model"]["metric"] == "r2"
    assert [i["column"] for i in a.card["importance"][:2]] == ["strong", "moderate"]
    assert a.card["verdict"] == "beats_baseline" and "mae" in a.card["model"]


def test_minimum_rows_are_enforced():
    df = planted.drivers(n=99)
    with pytest.raises(ApiError) as err:
        make_plan(planted.as_version(df), planted.card_for(df, "outcome"), ALL, "outcome")
    assert err.value.status == 422 and "at least 100 rows" in err.value.message and "99" in err.value.message


def test_a_short_target_name_leaves_out_only_columns_named_after_it():
    rng = np.random.default_rng(3)
    n = 200
    df = pd.DataFrame({"day": rng.integers(1, 29, n), "salary": rng.normal(50, 10, n).round(1),
                       "y_hat": rng.normal(0, 1, n).round(3), "y": rng.choice(["yes", "no"], n)})
    plan = make_plan(planted.as_version(df), planted.card_for(df, "y"), ALL, "y")
    assert set(plan.features) == {"day", "salary"}, plan.excluded
    assert [e["column"] for e in plan.excluded] == ["y_hat"]
    df = pd.DataFrame({"page_views": rng.integers(1, 500, n), "age_group": rng.choice(["young", "old"], n),
                       "age": rng.normal(40, 12, n).round(1)})
    plan = make_plan(planted.as_version(df), planted.card_for(df, "age"), ALL, "age")
    assert plan.features == ["page_views"] and [e["column"] for e in plan.excluded] == ["age_group"]
    df = planted.drivers()
    df["outcome_score"] = df["strong"]
    plan = make_plan(planted.as_version(df), planted.card_for(df, "outcome"), ALL, "outcome")
    assert "outcome_score" in {e["column"] for e in plan.excluded}  # a long name still matches anywhere


def test_a_forced_column_is_used_with_a_warning_and_turned_off_columns_are_listed():
    df = planted.drivers()
    chosen = ["strong", "moderate", "leak"]
    a = _analyze(df, "outcome", features=chosen, forced=chosen)
    assert "leak" in a.plan.features
    assert any(w["code"] == "forced_in" and "leak" in w["text"] for w in a.card["warnings"])
    excluded = {e["column"]: e["reason"] for e in a.card["excluded"]}
    assert excluded["noise"] == "turned off in the setup" and "ID" in excluded["code"]


def test_the_reproduction_code_gives_the_model_cards_numbers():
    a = _analyze(planted.drivers(), "outcome")
    again = repro.execute(a.code, planted.as_version(planted.drivers()))
    assert again["metrics"]["value"] == a.card["model"]["value"]
    assert "def reproduce(df, seed=42):" in a.code and "#   leak: records the outcome" in a.code or "#   leak:" in a.code


# --- the runs API ----------------------------------------------------------------------------------

def _planted_dataset(client) -> str:
    csv = planted.drivers().to_csv(index=False).encode()
    r = client.post(f"{API}/datasets", files={"file": ("planted.csv", csv, "text/csv")})
    assert r.status_code == 201, r.text
    ds = r.json()["id"]
    wait_status(client, ds, "offer", "ready")
    return ds


def _wait_run(client, rid, timeout=120):
    return wait_for(lambda: (r := client.get(f"{API}/runs/{rid}").json())["status"] in ("done", "failed", "cancelled") and r,
                    timeout=timeout, interval=0.2)


@pytest.mark.usefixtures("run_jobs")
def test_recipes_preview_run_results_code_and_cache(client):
    ds = _planted_dataset(client)
    recipes = {r["id"]: r for r in client.get(f"{API}/recipes", params={"dataset_id": ds}).json()}
    assert recipes["driver_analysis"]["compatible"] and recipes["driver_analysis"]["targets"][0] == "outcome"
    assert [m["id"] for m in recipes["driver_analysis"]["methods"]] == ["auto"]
    assert recipes["forecast"]["compatible"] is False and recipes["forecast"]["reason"] == "needs a date column"
    assert recipes["predict"]["compatible"] is False and recipes["predict"]["reason"]
    few = client.get(f"{API}/recipes", params={"dataset_id": ds, "scope": '{"rows": {"predicate": "strong > 2"}}'}).json()
    assert few[0]["compatible"] is False and "needs 100 rows" in few[0]["reason"]

    pre = client.post(f"{API}/datasets/{ds}/runs/preview", json={"recipe": "driver_analysis"}).json()
    assert pre["target"] == "outcome" and pre["task"] == "classification" and pre["metric"] == "accuracy"
    assert {e["column"] for e in pre["excluded"]} >= {"leak", "code"}
    assert set(pre["features"]) == {"strong", "moderate", "noise", "group"}
    assert len(pre["baselines"]) == 2 and pre["estimate_s"] >= 3 and pre["cached"] is None
    small = client.post(f"{API}/datasets/{ds}/runs/preview", json={"scope": {"rows": {"predicate": "strong > 2"}}})
    assert small.status_code == 422 and "at least 100 rows" in small.json()["error"]["message"]
    assert client.post(f"{API}/datasets/{ds}/runs", json={"recipe": "forecast"}).status_code == 422
    assert client.post(f"{API}/datasets/{ds}/runs", json={"method": "linear_regression"}).status_code == 422

    run = client.post(f"{API}/datasets/{ds}/runs", json={"recipe": "driver_analysis", "scope": {"columns": {"target": "outcome"}}}).json()
    assert run["status"] in ("queued", "running", "done")
    done = _wait_run(client, run["id"])
    assert done["status"] == "done", done
    card = done["model_card"]
    assert card["verdict"] == "beats_baseline" and card["importance"][0]["column"] == "strong"
    assert card["repro"]["code_path"] == f"runs/{run['id']}/repro.py" and card["fact_sheet_id"]
    assert done["summary"]["verdict"] == "beats_baseline"

    imp = client.get(f"{API}/runs/{run['id']}/results", params={"view": "importance"}).json()
    assert [c["name"] for c in imp["columns"]] == ["feature", "importance"] and imp["rows"][0][0] == "strong"
    base = client.get(f"{API}/runs/{run['id']}/results", params={"view": "baselines"}).json()
    assert base["rows"][-1][0].startswith("model:")
    pdp = client.get(f"{API}/runs/{run['id']}/results", params={"view": "partial_dependence", "feature": "strong"}).json()
    assert pdp["kind"] == "numeric" and pdp["rows"][0][1] < pdp["rows"][-1][1]  # more `strong`, more likely
    assert client.get(f"{API}/runs/{run['id']}/model-card").json()["verdict_text"] == card["verdict_text"]
    assert done["summary"]["views"] == ["importance", "confusion", "roc"]
    conf = client.get(f"{API}/runs/{run['id']}/results", params={"view": "confusion"}).json()
    assert [c["name"] for c in conf["columns"]] == ["actual", "predicted", "n"] and len(conf["rows"]) == 4
    assert sum(r[2] for r in conf["rows"]) == card["rows"]["train"]
    wrong_n = sum(r[2] for r in conf["rows"] if r[0] != r[1])
    assert wrong_n == card["misclassified"] > 0
    roc = client.get(f"{API}/runs/{run['id']}/results", params={"view": "roc"}).json()["rows"]
    assert roc[0][:2] == [0.0, 0.0] and roc[-1][:2] == [1.0, 1.0] and len(roc) <= 50
    assert abs(card["roc"]["auc"] - card["model"]["auc"]) < 0.03  # pooled out-of-fold vs the mean over folds
    wrong = client.post(f"{API}/runs/{run['id']}/wrong-rows")
    assert wrong.status_code == 201 and wrong.json()["row_count"] == wrong_n
    page = client.get(f"{API}/datasets/{ds}/rows", params={"selection": wrong.json()["selection_id"], "limit": 500}).json()
    assert page["total"] == wrong_n
    code = client.get(f"{API}/runs/{run['id']}/code").json()["python"]
    assert code.startswith("# Reproduces Sherlock run") and "def reproduce(df, seed=42):" in code

    t = time.perf_counter()
    again = client.post(f"{API}/datasets/{ds}/runs", json={"recipe": "driver_analysis", "scope": {"columns": {"target": "outcome"}}})
    assert time.perf_counter() - t < 0.5  # PRD ML-8: a repeat run is served from the cache (200 ms locally)
    assert again.json()["id"] == run["id"] and again.json()["status"] == "done"
    assert client.post(f"{API}/datasets/{ds}/runs/preview", json={}).json()["cached"] == run["id"]
    types = [e for e in client.get(f"{API}/jobs?dataset_id={ds}").json() if e["kind"] == "ml_run"]
    assert len(types) == 1


@pytest.mark.usefixtures("run_jobs")
def test_a_widget_becomes_the_analysis_and_goes_outdated_after_an_edit(client):
    ds = _planted_dataset(client)
    client.put(f"{API}/me/settings", json={"story_updates": "ask"})
    widget = client.post(f"{API}/datasets/{ds}/widgets", json={
        "scope": {"columns": {"x": "group"}}, "op": {"type": "sql", "sql": "SELECT \"group\", count(*) AS n FROM t WHERE {{rows}} GROUP BY 1"},
        "view": {"type": "bar"}, "title": "Rows by group"}).json()["widget"]
    run = client.post(f"{API}/datasets/{ds}/runs", json={"widget_id": widget["id"], "scope": {"columns": {"target": "outcome"}}}).json()
    assert _wait_run(client, run["id"])["status"] == "done"
    w = next(x for x in client.get(f"{API}/datasets/{ds}/widgets").json()["widgets"] if x["id"] == widget["id"])
    assert w["spec"]["op"]["type"] == "ml" and w["run_id"] == run["id"] and w["status"] == "ready"
    assert w["title"] == "What drives outcome?" and w["spec"]["view"]["options"]["chart_title"] == "Rows by group"
    data = client.get(f"{API}/widgets/{widget['id']}/data").json()
    assert data["rows"][0][0] == "strong" and data["run"]["summary"]["verdict"] == "beats_baseline"

    v = client.get(f"{API}/datasets/{ds}").json()["current_version"]
    client.post(f"{API}/datasets/{ds}/edits", json={"base_version": v, "edits": [{"row_id": 1, "column": "noise", "value": "9"}]})
    wait_for(lambda: client.get(f"{API}/runs/{run['id']}").json()["status"] == "outdated", timeout=60)
    w = wait_for(lambda: (x := client.get(f"{API}/widgets/{widget['id']}/data").json()) and x["run"]["status"] == "outdated" and x)
    assert w["rows"], "an outdated analysis still shows its last result"
    rerun = client.post(f"{API}/widgets/{widget['id']}/rerun").json()
    assert rerun["id"] != run["id"] and rerun["version"] == v + 1
    assert _wait_run(client, rerun["id"])["status"] == "done"
    undone = client.post(f"{API}/widgets/{widget['id']}/undo").json()
    assert undone["spec"]["op"]["type"] == "sql" and undone["title"] == "Rows by group"  # "Plain chart" goes back to the bar chart


@pytest.mark.usefixtures("run_jobs")
def test_the_builder_adds_the_driver_widget(client):
    ds = _planted_dataset(client)
    client.post(f"{API}/datasets/{ds}/use-as-is")
    wait_status(client, ds, "ready")
    widgets = client.get(f"{API}/datasets/{ds}/widgets").json()["widgets"]
    driver = next(w for w in widgets if w["spec"]["op"]["type"] == "ml")
    assert driver["title"] == "What drives outcome?" and driver["spec"]["view"]["type"] == "importance"
    assert _wait_run(client, driver["run_id"])["status"] == "done"
    layout = client.get(f"{API}/datasets/{ds}/widgets").json()["layout"]["lg"]
    assert any(it["i"] == driver["id"] for it in layout)
