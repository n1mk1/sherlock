"""Checks without code (PRD CLEAN-13): each rule kind finds what it says, bad rules are refused when
saved, a slow rule stops, and a rule's issue is counted, levelled, queued and fixed like any other."""

import pandas as pd
import pytest

from sherlock.cleaning import levels
from sherlock.cleaning import plan as plans
from sherlock.cleaning.loop import code_fix, rule_candidate
from sherlock.cleaning.rules import interpreter
from sherlock.cleaning.rules.kinds import RuleError, from_draft
from sherlock.profile.datacard import build_frame
from tests.test_jobs import API, wait_status

COLUMNS = {"amount": "float", "units": "int", "city": "category", "zone": "category", "code": "text",
           "start": "date", "end": "date"}


def frame():
    df = pd.DataFrame({
        "amount": ["10", "-3", "25", "40", "7", None],
        "units": ["1", "2", "2", "9", "4", "5"],
        "city": ["Oslo", "oslo ", "Bergen", "Paris", "Oslo", "Bergen"],
        "zone": ["N", "N", "W", "W", "S", "W"],
        "code": ["AB-12", "AB-13", "ab-1", "AB-99", "XX", "AB-55"],
        "start": ["2021-01-01", "2021-03-01", "2021-02-01", "2021-01-05", "2021-01-09", "2021-01-02"],
        "end": ["2021-01-10", "2021-02-01", "2021-02-03", "2021-01-06", "2021-01-08", "2021-01-12"],
    }, dtype=object)
    return build_frame(df, {})


def found(spec, max_s=2.0):
    rule = {"id": "r1", **interpreter.validate(spec, COLUMNS)}
    finding, error = interpreter.run(rule, frame(), max_s)
    return (finding.count if finding else 0), error


@pytest.mark.parametrize("spec,count", [
    ({"kind": "range", "column": "amount", "params": {"min": 0}}, 1),
    ({"kind": "range", "column": "units", "params": {"min": 1, "max": 5}}, 1),
    ({"kind": "date_window", "column": "start", "params": {"earliest": "2021-01-02", "latest": "2021-02-15"}}, 2),
    ({"kind": "allowed", "column": "city", "params": {"values": ["Oslo", "Bergen"]}}, 1),  # case and spacing ignored
    ({"kind": "pattern", "column": "code", "params": {"regex": "^[A-Z]{2}-[0-9]{2}$"}}, 2),
    ({"kind": "not_missing", "column": "amount", "params": {}}, 1),
    ({"kind": "unique", "column": "units", "params": {}}, 1),
    ({"kind": "order", "column": "end", "params": {"left": "start"}}, 2),
    ({"kind": "depends", "column": "zone", "params": {"from": "city"}}, 1),
])
def test_each_kind_finds_what_it_says(spec, count):
    assert found({**spec, "action": "flag"}) == (count, None)


@pytest.mark.parametrize("spec,field", [
    ({"kind": "range", "column": "city", "params": {"min": 0}}, "column"),           # a range on text
    ({"kind": "range", "column": "amount", "params": {}}, "params"),
    ({"kind": "range", "column": "amount", "params": {"min": 5, "max": 1}}, "params.min"),
    ({"kind": "date_window", "column": "start", "params": {"earliest": "soon"}}, "params.earliest"),
    ({"kind": "pattern", "column": "code", "params": {"regex": "[A-Z]+"}}, "params.regex"),      # not anchored
    ({"kind": "pattern", "column": "code", "params": {"regex": "^(a)\\1$"}}, "params.regex"),    # a back-reference
    ({"kind": "pattern", "column": "code", "params": {"regex": "^(a+)+$"}}, "params.regex"),     # nested repeats
    ({"kind": "order", "column": "end", "params": {"left": "nowhere"}}, "params.left"),
    ({"kind": "order", "column": "amount", "params": {"left": "start"}}, "params.left"),         # a number after a date
    ({"kind": "allowed", "column": "city", "params": {"values": []}}, "params.values"),
    ({"kind": "explode", "column": "city", "params": {}}, "kind"),
    ({"kind": "unique", "column": "nowhere", "params": {}}, "column"),
])
def test_a_bad_rule_is_refused_when_saved(spec, field):
    with pytest.raises(RuleError) as exc:
        interpreter.validate({**spec, "action": "flag"}, COLUMNS)
    assert exc.value.field == field


def test_a_slow_rule_stops_at_its_time_limit():
    assert found({"kind": "pattern", "column": "code", "params": {"regex": "^[A-Z]{2}-[0-9]{2}$"}, "action": "flag"},
                 max_s=0.0) == (0, interpreter.TOO_LONG)


def test_a_model_draft_becomes_a_rule():
    draft = {"kind": "order", "column": "end", "other": "start", "action": "quarantine", "min": None, "max": None}
    assert interpreter.validate(from_draft(draft), COLUMNS)["params"] == {"left": "start", "op": "<", "as": "date"}


def test_a_rules_issue_is_levelled_and_fixed_like_any_other():
    rule = {"id": "rul_1", **interpreter.validate({"kind": "range", "column": "amount", "params": {"min": 0},
                                                   "action": "quarantine"}, COLUMNS)}
    finding, _ = interpreter.run(rule, frame(), 2.0)
    issue = {"id": "iss_1", "detector": finding.detector, "column": finding.column, "count": finding.count,
             "severity": 0.1, "details": finding.details, "examples": finding.examples, "proposal": finding.proposal}
    card = {"columns": [{"name": "amount", "role": "measure", "type": "float"}], "target_candidates": [],
            "issues": [issue], "leakage_candidates": [], "id_columns": []}
    assert finding.detector == "rule:rul_1"
    assert levels.default_level(issue, card) == "breaks"  # a range is skews; on a measure, one up
    (item,) = plans.diagnose(card)
    assert item["key"] == "rule:rul_1|amount" and item["ticked"] and item["change"]
    fix = rule_candidate(issue)  # quarantine: a domain rule, with its own fix
    assert fix is not None and "quarantine_rows(df, bad, 'check: amount')" in fix.code and code_fix(issue) is None
    flagged = interpreter.proposal({**rule, "action": "flag"})
    flag = {**issue, "details": {**issue["details"], "never_change": flagged, "domain_rule": None}}
    assert plans.never_change(flag, card)[0] == "Listed for your review, not changed: rows where it isn't true that amount is at least 0."


@pytest.fixture
def jobs_on(run_jobs):
    pass


@pytest.mark.usefixtures("jobs_on")
def test_a_check_is_saved_counted_and_added_to_the_plan(client):
    ds = client.post(f"{API}/datasets/sample").json()
    wait_status(client, ds["id"], "offer")
    plan = client.post(f"{API}/datasets/{ds['id']}/clean/plan", json={}).json()
    bad = client.post(f"{API}/datasets/{ds['id']}/rules", json={"kind": "range", "column": "name", "params": {"min": 0}})
    assert bad.status_code == 422 and "column" in bad.json()["error"]["message"]
    r = client.post(f"{API}/datasets/{ds['id']}/rules",
                    json={"kind": "range", "column": "fare", "params": {"min": 0, "max": 500}, "action": "flag"})
    assert r.status_code == 201
    rule = r.json()
    assert rule["status"] == "active" and rule["source"] == "user" and rule["count"] > 0 and rule["error"] is None
    assert rule["words"] == "fare is between 0 and 500"
    items = client.get(f"{API}/clean-plans/{plan['id']}").json()["items"]
    mine = next(i for i in items if i["key"] == f"rule:{rule['id']}|fare")
    assert mine["count"] == rule["count"] and not mine["change"]  # flagged: listed, never changed
    assert client.get(f"{API}/datasets/{ds['id']}/rules").json()["rules"][0]["id"] == rule["id"]
    off = client.patch(f"{API}/rules/{rule['id']}", json={"status": "off"}).json()
    assert off["status"] == "off" and off["count"] is None
    assert not any(i["key"] == f"rule:{rule['id']}|fare" for i in client.get(f"{API}/clean-plans/{plan['id']}").json()["items"])
    # From the plan: add_rule saves the check and adds its item, with the other ops, all or nothing.
    patched = client.patch(f"{API}/clean-plans/{plan['id']}", json={"ops": [
        {"op": "add_rule", "rule": {"kind": "unique", "column": "ticket", "params": {}, "action": "quarantine"}}]}).json()
    assert patched["summary"] == "Added your check: ticket is unique."
    assert any(i["key"].startswith("rule:") and i["column"] == "ticket" for i in patched["items"])
    refused = client.patch(f"{API}/clean-plans/{plan['id']}", json={"ops": [
        {"op": "add_rule", "rule": {"kind": "range", "column": "fare", "params": {}, "action": "flag"}}]})
    assert refused.status_code == 422 and len(client.get(f"{API}/datasets/{ds['id']}/rules").json()["rules"]) == 2
