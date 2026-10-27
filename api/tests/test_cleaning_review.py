"""The background review (PRD CLEAN-8c, TRD §7.2): Super's levels and reasons, checked and floored by
code, stored per version, and the plan's fallback to code's default levels."""

import json
import re
from dataclasses import replace
from types import SimpleNamespace

import pytest

from sherlock.cleaning import registry, review
from sherlock.cleaning.review import _check_refs, findings, rated
from sherlock.config import get_settings
from sherlock.llm.client import StructuredOutputError
from sherlock.llm.schemas import Rating, Ratings
from tests.test_jobs import API, wait_for, wait_status

CARD = {
    "row_count": 100,
    "columns": [{"name": "outcome", "role": "target_like", "type": "category"},
                {"name": "amount", "role": "measure", "type": "float"},
                {"name": "group", "role": "dimension", "type": "category"},
                {"name": "code", "role": "id", "type": "id"}],
    "target_candidates": ["outcome"], "leakage_candidates": [{"column": "group", "target": "outcome", "reason": "r"}],
    "id_columns": ["code"],
}


def issue(detector, column, severity=0.1):
    return {"id": f"iss_{detector}_{column}", "detector": detector, "column": column, "count": 4, "severity": severity,
            "details": {}, "examples": ["a", "b"], "proposal": "Do the thing."}


def test_likely_real_makes_it_worth_a_look_but_the_floor_holds_on_a_measure():
    on_measure, on_category = issue("sentinels", "amount"), issue("whitespace_case", "outcome")
    assert rated(on_measure, CARD, "cosmetic", "Pulls averages down.", False)["sev"] == "skews"  # floored
    assert rated(on_measure, CARD, "breaks", "Pulls averages down.", True)["sev"] == "skews"     # floor beats likely_real
    other = {**CARD, "target_candidates": [], "columns": [{"name": "outcome", "role": "dimension", "type": "category"}]}
    assert rated(on_category, other, "breaks", "Splits the groups.", True)["sev"] == "check"
    assert rated(on_category, other, "cosmetic", "Changes nothing.", False) == {
        "sev": "cosmetic", "sev_reason": "Changes nothing.", "sev_source": "model", "likely_real": False}


def test_a_reason_with_digits_or_causal_wording_is_dropped_but_the_level_stays():
    i = issue("whitespace_case", "outcome")
    assert rated(i, CARD, "skews", "Three groups would split.", False)["sev_reason"] is None
    assert rated(i, CARD, "skews", "About 4 groups split.", False)["sev_reason"] is None
    got = rated(i, CARD, "skews", "This leads to wrong counts.", False)
    assert got["sev_reason"] is None and got["sev"] == "skews"


def test_leakage_and_id_findings_are_never_sent():
    card = {**CARD, "issues": [issue("leakage", "group"), issue("missing", "group"), issue("whitespace_case", "code"),
                               issue("sentinels", "code"), issue("missing", "amount", 0.5), issue("missing", "amount", 0.1)]}
    sent = [(i["detector"], i["column"], i["severity"]) for i in findings(card)]
    # Leakage, anything on its column and non-type fixes on the ID column are left out; one per key, the most severe.
    assert sent == [("missing", "amount", 0.5), ("sentinels", "code", 0.1)]


def test_every_ref_must_be_rated_once():
    check = _check_refs(["f1", "f2"])
    ok = Ratings(ratings=[Rating(ref=r, level="check", reason="Fine.", likely_real=False) for r in ("f1", "f2")])
    check(ok)
    for refs in (["f1"], ["f1", "f2", "f2"], ["f1", "f2", "f3"]):
        with pytest.raises(ValueError):
            check(Ratings(ratings=[Rating(ref=r, level="check", reason="Fine.", likely_real=False) for r in refs]))


class ScriptedLLM:
    """Rates every ref it is sent "cosmetic", except that the calls in `fail` raise."""

    calls: list[str] = []
    fail: set[int] = set()

    def __init__(self, settings=None):
        pass

    def structured(self, role, messages, schema, **kw):
        ScriptedLLM.calls.append(kw["purpose"])
        if len(ScriptedLLM.calls) in ScriptedLLM.fail:
            raise StructuredOutputError("still invalid after the repair")
        refs = re.findall(r"^(f\d+) · ", messages[1]["content"], re.M)
        value = Ratings(ratings=[Rating(ref=r, level="cosmetic", reason="Changes no answer.", likely_real=False)
                                 for r in refs])
        kw["validate"](value)
        return SimpleNamespace(value=value)


@pytest.fixture
def reviews_on(monkeypatch, tmp_path, run_jobs):
    (tmp_path / "none.json").write_text("[]", encoding="utf-8")
    monkeypatch.setenv("CLEAN_REVIEW", "on")
    monkeypatch.setenv("LLM_MOCK", str(tmp_path / "none.json"))  # a model "answers", so the review runs
    monkeypatch.setattr(review, "LLMClient", ScriptedLLM)
    ScriptedLLM.calls, ScriptedLLM.fail = [], set()
    get_settings.cache_clear()


def _reviewed_plan(client):
    ds = client.post(f"{API}/datasets/sample").json()
    wait_status(client, ds["id"], "offer")
    wait_for(lambda: all(j["status"] == "done" for j in client.get(f"{API}/jobs", params={"dataset_id": ds["id"]}).json()
                         if j["kind"] == "review_issues") and ScriptedLLM.calls)
    return ds, client.post(f"{API}/datasets/{ds['id']}/clean/plan", json={}).json()


@pytest.mark.usefixtures("reviews_on")
def test_the_review_rates_the_plan_and_runs_once_per_version(client):
    ds, plan = _reviewed_plan(client)
    assert plan["review"] == "ready"
    rated_items = [i for i in plan["items"] if i["change"]]
    assert rated_items and all(i["sev_source"] == "model" and i["sev_reason"] == "Changes no answer." for i in rated_items)
    # On the target or a measure the floor holds: never below the detector's own default.
    for i in rated_items:
        default = registry.get(i["detector"]).default_level
        assert i["sev"] == "cosmetic" or i["sev"] == default
    assert all(i["sev"] is None for i in plan["items"] if not i["change"])  # leakage and IDs: never rated
    calls = len(ScriptedLLM.calls)
    again = client.post(f"{API}/datasets/{ds['id']}/clean/plan", json={}).json()
    assert again["review"] == "ready" and len(ScriptedLLM.calls) == calls  # stored: no second review
    jobs = [j for j in client.get(f"{API}/jobs", params={"dataset_id": ds["id"]}).json() if j["kind"] == "review_issues"]
    assert len(jobs) == 1


@pytest.mark.usefixtures("reviews_on")
def test_a_changed_detector_version_drops_its_ratings(client, monkeypatch):
    ds, plan = _reviewed_plan(client)
    detector = next(i["detector"] for i in plan["items"] if i["change"])
    spec = registry.get(detector)
    monkeypatch.setitem(registry._specs, detector, replace(spec, version=spec.version + 1))
    from sherlock.db.connection import connect

    db = connect(get_settings())
    try:
        got = review.stored(db, ds["id"], plan["version"])
    finally:
        db.close()
    assert got is not None and not any(k.startswith(f"{detector}|") for k in got)


@pytest.mark.usefixtures("reviews_on")
def test_a_failed_chunk_keeps_its_defaults_and_is_not_retried(client):
    ScriptedLLM.fail = {1}
    ds, plan = _reviewed_plan(client)
    assert plan["review"] == "default"  # every chunk failed: code's levels, recorded so it isn't asked again
    assert all(i["sev_source"] == "default" for i in plan["items"] if i["change"])
    calls = len(ScriptedLLM.calls)
    client.post(f"{API}/datasets/{ds['id']}/clean/plan", json={})
    assert len(ScriptedLLM.calls) == calls


@pytest.fixture
def review_on_no_model(monkeypatch, run_jobs):
    monkeypatch.setenv("CLEAN_REVIEW", "on")  # on, but LLM_BASE_URL is empty and nothing is recorded
    get_settings.cache_clear()


@pytest.mark.usefixtures("review_on_no_model")
def test_with_no_model_the_plan_opens_on_default_levels(client):
    ds = client.post(f"{API}/datasets/sample").json()
    wait_status(client, ds["id"], "offer")
    plan = client.post(f"{API}/datasets/{ds['id']}/clean/plan", json={}).json()
    assert plan["review"] == "default"
    assert all(i["sev_source"] == "default" and i["sev"] for i in plan["items"] if i["change"])
    assert not [j for j in client.get(f"{API}/jobs", params={"dataset_id": ds["id"]}).json() if j["kind"] == "review_issues"]


@pytest.mark.usefixtures("reviews_on")
def test_a_started_plan_is_not_changed_by_a_later_review(client):
    from sherlock.cleaning import plan as plans
    from sherlock.db.connection import connect

    ds, plan = _reviewed_plan(client)
    db = connect(get_settings())
    try:
        row = plans.get(db, plan["id"])
        plans.set_status(db, plan["id"], "started")
        before = row["items_json"]
        db.execute("DELETE FROM issue_reviews WHERE dataset_id = ?", (ds["id"],))
        dataset = db.execute("SELECT * FROM datasets WHERE id = ?", (ds["id"],)).fetchone()
        from sherlock.jobs.review import _run

        ctx = SimpleNamespace(db=db, dataset_id=ds["id"], params={"version": plan["version"]}, settings=get_settings(),
                              cache=client.app.state.duckdb, bus=None, id=None, log=lambda *a, **k: None,
                              progress=lambda *a, **k: None)
        _run(ctx)
        assert plans.get(db, plan["id"])["items_json"] == before
        assert json.loads(before) and dataset is not None
    finally:
        db.close()
