"""The background review (PRD CLEAN-8c, TRD §7.2): Super's levels and reasons, checked and floored by
code, stored per version, and the plan's fallback to code's default levels."""

import json
import re
from dataclasses import replace
from types import SimpleNamespace

import pytest

from sherlock.cleaning import registry, review
from sherlock.cleaning.rules import service as review_rules
from sherlock.cleaning.review import _check_refs, findings, rated
from sherlock.config import get_settings
from sherlock.llm.client import StructuredOutputError
from sherlock.llm.schemas import Rating, Ratings, RuleSuggestions
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
    """Rates every ref it is sent "cosmetic", except that the rating calls in `fail` (counted from 1) raise;
    suggests the checks in `suggestions`."""

    calls: list[str] = []
    fail: set[int] = set()
    suggestions: list[dict] = []

    def __init__(self, settings=None):
        pass

    def structured(self, role, messages, schema, **kw):
        ScriptedLLM.calls.append(kw["purpose"])
        if kw["purpose"] == "suggest_rules":
            return SimpleNamespace(value=RuleSuggestions(suggestions=ScriptedLLM.suggestions))
        if ScriptedLLM.calls.count("rate") in ScriptedLLM.fail:
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
    ScriptedLLM.calls, ScriptedLLM.fail, ScriptedLLM.suggestions = [], set(), []
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
    ScriptedLLM.fail = {1, 2}  # both of the chunk's rating calls
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


def draft(kind, column, **params):
    base = {"kind": kind, "column": column, "min": None, "max": None, "earliest": None, "latest": None,
            "values": None, "regex": None, "other": None, "action": "flag"}
    return {"rule": {**base, **params}, "reason": "Families aboard are small, so a bigger count is a typo."}


@pytest.mark.usefixtures("reviews_on")
def test_suggested_checks_are_checked_counted_and_kept_or_dismissed(client):
    ScriptedLLM.suggestions = [
        draft("range", "parch", max=5.0, action="quarantine"),  # valid: some rows break it
        draft("range", "nowhere", max=5.0),             # not a column: dropped
        draft("not_missing", "age"),                    # repeats the built-in missing values on age: dropped
        draft("range", "parch", max=4.0),               # the same kind on the same column again: dropped
        {**draft("unique", "ticket"), "reason": "Has 2 problems."},  # kept, but its reason has digits: dropped
    ]
    ds, plan = _reviewed_plan(client)
    got = plan["suggestions"]
    assert [(s["kind"], s["column"]) for s in got] == [("range", "parch"), ("unique", "ticket")]
    parch = got[0]
    assert parch["status"] == "suggested" and parch["source"] == "suggested" and parch["count"] > 0
    assert parch["words"] == "parch is at most 5" and parch["reason"].startswith("Families aboard")
    assert parch["sev"] == "cosmetic" and parch["sev_reason"] == "Changes no answer."  # rated with the rest
    assert got[1].get("reason") is None
    assert not any(i["key"].startswith("rule:") for i in plan["items"])  # not run by the Cleaner until kept

    # Its threshold is a suggestion: edited before keeping it, it stays a suggestion with the new count.
    edited = client.patch(f"{API}/rules/{parch['id']}", json={"params": {"max": 4}})
    assert edited.status_code == 200 and edited.json()["status"] == "suggested" and edited.json()["words"] == "parch is at most 4"
    now = client.get(f"{API}/clean-plans/{plan['id']}").json()["suggestions"][0]
    assert now["words"] == "parch is at most 4" and now["count"] >= parch["count"]
    bad = client.patch(f"{API}/rules/{parch['id']}", json={"params": {"max": "lots"}})
    assert bad.status_code == 422
    kept = client.patch(f"{API}/clean-plans/{plan['id']}", json={"ops": [{"op": "keep_suggestion", "rule_id": parch["id"]}]})
    assert kept.status_code == 200 and kept.json()["summary"] == "Kept the suggested check: parch is at most 4."
    item = next(i for i in kept.json()["items"] if i["key"] == f"rule:{parch['id']}|parch")
    assert item["count"] == now["count"]
    gone = client.patch(f"{API}/clean-plans/{plan['id']}", json={"ops": [{"op": "dismiss_suggestion", "rule_id": got[1]["id"]}]})
    assert gone.json()["summary"] == "Dismissed the suggested check: ticket is unique." and gone.json()["suggestions"] == []
    again = client.patch(f"{API}/clean-plans/{plan['id']}", json={"ops": [{"op": "keep_suggestion", "rule_id": got[1]["id"]}]})
    assert again.status_code == 422

    # A dismissed suggestion isn't suggested again: the same kind on the same column is dropped.
    from sherlock.db.connection import connect
    from sherlock.profile import service as profile_service

    db = connect(get_settings())
    try:
        dataset = db.execute("SELECT * FROM datasets WHERE id = ?", (ds["id"],)).fetchone()
        card = profile_service.get_or_build(get_settings(), db, client.app.state.duckdb, dataset)
        frame = review_rules.frame_for(get_settings(), client.app.state.duckdb, db, dataset)
        assert review.suggest(get_settings(), db, dataset, card, frame, None, ScriptedLLM()) == []
    finally:
        db.close()


def test_two_ratings_keep_the_more_severe_level_of_each_finding(monkeypatch):
    """One call's lighter reading can't move a finding down (PRD CLEAN-8c): of the two ratings, the more severe."""
    calls = []
    replies = [
        Ratings(ratings=[Rating(ref="f1", level="cosmetic", reason="Changes nothing.", likely_real=False),
                         Rating(ref="f2", level="check", reason="Looks real.", likely_real=True)]),
        Ratings(ratings=[Rating(ref="f1", level="splits", reason="Splits the groups.", likely_real=False),
                         Rating(ref="f2", level="cosmetic", reason="Changes nothing.", likely_real=False)]),
    ]

    class Two:
        def structured(self, role, messages, schema, **kw):
            calls.append(kw["purpose"])
            return SimpleNamespace(value=replies[len(calls) - 1])

    stored = {}

    class DB:
        def execute(self, *a):
            return self

        def fetchall(self):
            return []  # no earlier ratings

        def executemany(self, sql, rows):
            stored.update({r[2]: r for r in rows})

    card = {"version": 2, "row_count": 100, "columns": [{"name": "outcome", "role": "dimension", "type": "category"},
                                          {"name": "amount", "role": "dimension", "type": "float"}],
            "target_candidates": [], "leakage_candidates": [], "id_columns": [],
            "issues": [issue("whitespace_case", "outcome", 0.3), issue("outliers", "amount", 0.2)]}
    assert review.review(get_settings(), DB(), {"id": "ds", "user_id": "u"}, card, None, llm=Two()) == "ready"
    assert calls == ["rate", "rate"]
    assert stored["whitespace_case|outcome"][4:6] == ("splits", "Splits the groups.")
    assert stored["outliers|amount"][4] == "check"  # check (likely real) is more severe than cosmetic


@pytest.mark.usefixtures("reviews_on")
def test_a_second_review_reuses_the_ratings_of_identical_findings(client):
    ds, plan = _reviewed_plan(client)
    from sherlock.db.connection import connect
    from sherlock.profile import service as profile_service

    db = connect(get_settings())
    try:
        dataset = db.execute("SELECT * FROM datasets WHERE id = ?", (ds["id"],)).fetchone()
        card = profile_service.get_or_build(get_settings(), db, client.app.state.duckdb, dataset, plan["version"])
        first = review.stored(db, ds["id"], plan["version"])
        rated = ScriptedLLM.calls.count("rate")
        assert review.review(get_settings(), db, dataset, card, None, llm=ScriptedLLM()) == "ready"
        assert ScriptedLLM.calls.count("rate") == rated  # every finding was rated before: no model call
        assert review.stored(db, ds["id"], plan["version"]) == first
    finally:
        db.close()


def test_a_picked_date_order_is_codes_own_parse():
    from sherlock.cleaning.loop import order_candidate

    fix = order_candidate({"detector": "ambiguous_dates", "column": "visit_date", "date_order": "dmy"})
    assert fix.label == "Parse dates day-first (dd/mm/yyyy)"
    assert "parse_dates_smart(df['visit_date'], order_hint='dmy')" in fix.code and "quarantine_rows(" in fix.code
    compile(fix.code, "fix", "exec")
    assert order_candidate({"detector": "ambiguous_dates", "column": "visit_date", "date_order": None}) is None
