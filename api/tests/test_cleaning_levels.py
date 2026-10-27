"""Severity levels without a model (PRD CLEAN-8c, CLEAN-6): code's default level for an issue, the
queue by level, and the report's lines by skip kind."""

from sherlock.cleaning import plan as plans
from sherlock.cleaning.levels import default_level
from sherlock.cleaning.loop import SKIP_KINDS, queue
from sherlock.cleaning.report import _outcomes

CARD = {
    "columns": [{"name": "outcome", "role": "target_like"}, {"name": "amount", "role": "measure"},
                {"name": "notes", "role": "free_text"}, {"name": "group", "role": "dimension"},
                {"name": "start", "role": "time"}, {"name": "end", "role": "time"}],
    "target_candidates": ["outcome"],
}


def issue(detector, column, severity=0.1, **details):
    return {"id": f"iss_{detector}_{column}", "detector": detector, "column": column, "count": 3,
            "severity": severity, "details": details, "examples": [], "proposal": ""}


def test_the_target_and_measures_go_up_a_level_and_free_text_down():
    assert default_level(issue("sentinels", "group"), CARD) == "skews"
    assert default_level(issue("sentinels", "amount"), CARD) == "breaks"
    assert default_level(issue("numbers_as_text", "outcome"), CARD) == "breaks"
    assert default_level(issue("numbers_as_text", "notes"), CARD) == "splits"
    assert default_level(issue("whitespace_case", "notes"), CARD) == "cosmetic"
    assert default_level(issue("whitespace_case", "group"), CARD) == "splits"
    assert default_level(issue("whitespace_case", "amount"), CARD) == "skews"


def test_observations_rows_and_marked_columns_take_no_adjustment():
    assert default_level(issue("outliers", "amount"), CARD) == "check"  # worth a look whatever the column
    assert default_level(issue("missing", "outcome"), CARD) == "check"
    assert default_level(issue("duplicates", None), CARD) == "skews"   # whole rows
    assert default_level(issue("leakage", "group"), CARD) is None
    assert default_level(issue("gone_check", "amount"), CARD) == "check"  # a removed detector


def test_a_finding_over_several_columns_takes_the_most_important_role():
    assert default_level(issue("cross_column", "end", earlier="start", later="end"), CARD) == "skews"
    assert default_level(issue("cross_column", "end", earlier="amount", later="end"), CARD) == "breaks"


def test_the_plan_carries_default_levels():
    card = {**CARD, "issues": [issue("sentinels", "amount"), issue("leakage", "group", target="outcome", reason="r")],
            "leakage_candidates": [], "id_columns": []}
    items = {i["detector"]: i for i in plans.diagnose(card)}
    assert (items["sentinels"]["sev"], items["sentinels"]["sev_source"]) == ("breaks", "default")
    assert items["leakage"]["sev"] is None and items["leakage"]["sev_source"] is None
    assert plans.run_params(list(items.values()))["levels"] == {"sentinels|amount": "breaks"}


def test_the_queue_goes_by_level_then_severity():
    issues = [issue("outliers", "amount", 0.5), issue("whitespace_case", "group", 0.3),
              issue("sentinels", "amount", 0.01), issue("leakage", "group", 1.0)]
    order = [i["detector"] for i in queue(issues, CARD)]
    # Never-changed first (skipped at once), then breaks, splits, and the observation last.
    assert order == ["leakage", "sentinels", "whitespace_case", "outliers"]


def test_runs_before_holds_whatever_the_levels():
    issues = [issue("impossible_values", "amount", 0.3), issue("sentinels", "amount", 0.01)]
    levels = {"impossible_values|amount": "breaks", "sentinels|amount": "cosmetic"}  # the plan's levels
    assert [i["detector"] for i in queue(issues, CARD, levels)] == ["sentinels", "impossible_values"]
    # It only moves up: placeholders already ahead of their rule stay where they are.
    levels = {"impossible_values|amount": "check", "sentinels|amount": "breaks"}
    assert [i["detector"] for i in queue(issues, CARD, levels)] == ["sentinels", "impossible_values"]


def test_each_skip_kind_lands_on_its_report_line():
    state = {"skipped": [{"skip_kind": k} for k in SKIP_KINDS] + [{"reason": "an old run, no kind"}],
             "handled": ["missing|age"]}
    lines = _outcomes(state, {"missing|age", "outliers|fare", "whitespace_case|name"})
    assert lines == {"checked_and_kept": 1, "couldnt_fix": 5, "kept_by_design": 1,
                     "not_attempted": 3 + 2}  # unticked, needs_choice, budget, and two keys never reached
