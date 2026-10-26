import re

import numpy as np
import pandas as pd
import pytest

from sherlock.cleaning import gate
from sherlock.cleaning.helpers import (
    canonicalize_categories, extract_pattern, fill_by_group, fix_encoding, flag_rows, normalize_whitespace_case,
    parse_dates_smart, parse_failures, parse_numbers, quarantine_rows, strip_sentinels,
)
from sherlock.cleaning.verifiers import verify


def frame(**cols) -> pd.DataFrame:
    n = len(next(iter(cols.values())))
    return pd.DataFrame({"_row_id": range(1, n + 1), "_quarantine_reason": [None] * n, **cols})


# --- helpers -----------------------------------------------------------------------------------


def test_strip_sentinels():
    s = pd.Series(["a", "N/A", " null ", None, "-", "b", "-999"], dtype=object)
    assert strip_sentinels(s).isna().tolist() == [False, True, True, True, True, False, False]
    assert strip_sentinels(s, extra=[-999]).isna().tolist()[-1]
    nums = pd.Series([1.0, -999.0, 3.0])
    assert strip_sentinels(nums, extra=[-999]).isna().tolist() == [False, True, False]


def test_parse_numbers():
    s = pd.Series(["$1,200.50", "(300)", "45%", "1 000", "abc", None, "12-", "€ 7"], dtype=object)
    out = parse_numbers(s)
    assert out.tolist()[:4] == [1200.5, -300.0, 45.0, 1000.0] and np.isnan(out[4])
    assert out[6] == -12.0 and out[7] == 7.0
    assert parse_failures(s, out).tolist() == [False, False, False, False, True, False, False, False]
    eu = pd.Series(["1.234,5", "2,25", "10"], dtype=object)
    assert parse_numbers(eu).tolist() == [1234.5, 2.25, 10.0]
    assert parse_numbers(pd.Series(["1,5"]), locale_hint="de").tolist() == [1.5]


def test_parse_dates_smart():
    s = pd.Series(["2024-01-05", "05/02/2024", "31/12/2023", "not a date", None], dtype=object)
    out = parse_dates_smart(s, order_hint="dmy")
    assert out[0] == pd.Timestamp("2024-01-05") and out[1] == pd.Timestamp("2024-02-05")
    assert out[2] == pd.Timestamp("2023-12-31") and pd.isna(out[3]) and pd.isna(out[4])
    mdy = parse_dates_smart(pd.Series(["02/05/2024", "12/31/2023"], dtype=object))
    assert mdy.tolist() == [pd.Timestamp("2024-02-05"), pd.Timestamp("2023-12-31")]


def test_text_helpers():
    s = pd.Series(["  New  York", "new york", "New York", "Boston ", None], dtype=object)
    assert normalize_whitespace_case(s).tolist()[:4] == ["New York"] * 3 + ["Boston"]
    assert normalize_whitespace_case(s, mode="upper").tolist()[3] == "BOSTON"
    named = pd.Series(["North", "north", "North", " NORTH"], dtype=object, name="region")  # as the Cleaner's code passes it
    assert normalize_whitespace_case(named).tolist() == ["North"] * 4
    cats = pd.Series(["Southampton"] * 5 + ["Southamptn", "Cherbourg", "Cherbourg"], dtype=object)
    assert canonicalize_categories(cats).tolist().count("Southampton") == 6
    assert canonicalize_categories(cats, mapping={"Cherbourg": "C"}).tolist()[-1] == "C"
    assert extract_pattern(pd.Series(["C22 C26", "B5", None], dtype=object), r"^([A-Z])").tolist()[:2] == ["C", "B"]
    assert fix_encoding(pd.Series(["CafÃ©", "ok", 3], dtype=object)).tolist() == ["Café", "ok", 3]


def test_fill_by_group_and_row_helpers():
    df = frame(title=["Mr", "Mr", "Mrs", "Mrs", "Dr"], age=[30.0, None, 40.0, None, None])
    filled = fill_by_group(df, "age", "title")
    assert filled.tolist() == [30.0, 30.0, 40.0, 40.0, 35.0]  # Dr has no ages: the overall median
    q = quarantine_rows(df, df["age"].isna(), "missing age")
    assert q["_quarantine_reason"].tolist() == [None, "missing age", None, "missing age", "missing age"]
    assert df["_quarantine_reason"].isna().all()  # never in place
    f = flag_rows(df, df["title"] == "Dr", "check title")
    assert f.attrs["sherlock_flags"] == {"check title": [5]} and f.equals(df)


# --- verifiers ---------------------------------------------------------------------------------


def test_verify_good_imputation():
    before = frame(title=["Mr", "Mr", "Mrs", "Mrs"] * 10, age=[30.0, None, 40.0, 42.0] * 10)
    after = before.assign(age=fill_by_group(before, "age", "title"))
    r = verify(before, after, "missing", "age")
    assert r.passed and r.issue_before == 10 and r.issue_after == 0
    assert r.soft["resolved"] == 1.0 and r.cells_changed == 10 and r.unrelated_changed == 0
    assert 0.5 < r.score <= 1.0


def test_verify_rejects_dropped_rows_and_silent_blanks():
    before = frame(x=["1", "2", "oops", "4"])
    assert verify(before, before.iloc[:3], "mixed_types", "x").hard["row_ledger"].startswith("fail")
    # Parsing without quarantining the failure: the value silently became empty.
    bad = before.assign(x=pd.to_numeric(before["x"], errors="coerce"))
    r = verify(before, bad, "mixed_types", "x")
    assert not r.passed and r.hard["nan_introduced"].startswith("fail") and r.hard["parse_quarantine"].startswith("fail")
    assert r.score == 0.0
    # The same parse with the failure quarantined passes.
    parsed = pd.to_numeric(before["x"], errors="coerce")
    good = quarantine_rows(before.assign(x=parsed), parse_failures(before["x"], parsed), "parse: x")
    r = verify(before, good, "mixed_types", "x")
    assert r.passed and r.quarantined == 1 and r.parse_rate == 1.0


def test_verify_allows_placeholders_to_become_missing_and_catches_mixed_types():
    before = frame(x=["a", "N/A", "b", "-"])
    assert verify(before, before.assign(x=strip_sentinels(before["x"])), "sentinels", "x").passed
    mixed = before.assign(x=pd.Series(["a", 1, "b", 2.5], dtype=object))
    assert verify(before, mixed, None, "x").hard["dtype"].startswith("fail")
    removed = before.drop(columns=["x"])
    assert verify(before, removed, None, "x").hard["pandera"].startswith("fail: columns removed")


def test_verify_counts_unrelated_changes():
    before = frame(a=["x", "y", "z", "w"], b=["1", "2", "3", "4"])
    after = before.assign(a=["X", "Y", "Z", "W"], b=["9", "2", "3", "4"])
    r = verify(before, after, None, "a")
    assert r.cells_changed == 5 and r.unrelated_changed == 1 and r.soft["unrelated"] < 1.0


# --- gate --------------------------------------------------------------------------------------


@pytest.mark.parametrize(("scores", "agree", "clean", "changed", "expected"), [
    ([0.95, 0.9], 1.0, True, 10, "commit"),          # 0.57 + 0.2 + 0.2
    ([0.95, 0.9], 1.0, True, 300, "flag"),           # blast 0.3 ≥ 0.2
    ([0.8, 0.2], 0.5, False, 10, "flag"),            # 0.48 + 0.1 + 0 = 0.58
    ([0.0, 0.0], 1.0, True, 0, "skip"),
    ([0.7, 0.65], 1.0, False, 5, "flag"),            # 0.42 + 0.2 + 0 = 0.62
    ([0.5], 1.0, False, 5, "skip"),                  # 0.30 + 0.2 = 0.50
    ([0.95, 0.9], 0.5, True, 10, "commit"),          # 0.57 + 0.1 + 0.2 = 0.87: one other result differs
    ([0.85, 0.85, 0.8], 1 / 3, True, 10, "flag"),    # 0.51 + 0.067 + 0.2 = 0.78: three different results
])
def test_gate(scores, agree, clean, changed, expected):
    d = gate.decide(scores, agree, clean, changed, 1000)
    assert d.gate == expected and d.agreement == agree
    assert d.confidence == pytest.approx(0.6 * max(scores) + 0.2 * agree + 0.2 * clean, abs=1e-4)


def test_quarantined_rows_count_as_all_their_cells_in_the_blast():
    # The live Titanic run (2026-10-25): a step quarantined 1,020 of 1,309 rows × 14 columns. Counted
    # as one cell each that was a 5.6% blast; it is 78% of the data.
    total = 1309 * 14
    affected = gate.cells_affected(0, 1020, 14, total)
    assert affected == 1020 * 14
    d = gate.decide([0.95, 0.9], 1.0, True, affected, total)
    assert d.gate == "flag" and d.reason == "changes more than a fifth of the data"
    assert gate.cells_affected(120, 1, 4, 480) == 124
    assert gate.cells_affected(480, 120, 4, 480) == 480  # capped


# --- helpers inside the sandbox ----------------------------------------------------------------


def test_helpers_run_in_the_sandbox_and_types_survive(tmp_path):
    import duckdb

    from sherlock.config import get_settings
    from sherlock.sandbox.runner import execute

    src, out = tmp_path / "in.parquet", tmp_path / "out.parquet"
    duckdb.sql(
        "SELECT * FROM (VALUES (1::BIGINT, NULL::VARCHAR, 'Mr', 30.0, 7::BIGINT, DATE '2024-01-02'), "
        "(2, NULL, 'Mr', NULL, NULL, DATE '2024-01-03'), (3, NULL, 'Mrs', 40.0, 9, NULL)) "
        "t(_row_id, _quarantine_reason, title, age, body, day)"
    ).write_parquet(str(src))
    code = "result = flag_rows(df.assign(age=fill_by_group(df, 'age', 'title')), df['title'] == 'Mrs', 'check')\n"
    r = execute(get_settings(), code, src, out)
    assert r.ok, r.error
    assert r.flags == {"check": [3]}
    types = {c: t for c, t, *_ in duckdb.sql(f"DESCRIBE SELECT * FROM read_parquet('{out.as_posix()}')").fetchall()}
    assert (types["body"], types["day"], types["_quarantine_reason"], types["_row_id"]) == ("BIGINT", "DATE", "VARCHAR", "BIGINT")
    assert duckdb.sql(f"SELECT age FROM read_parquet('{out.as_posix()}') ORDER BY _row_id").fetchall() == [(30.0,), (30.0,), (40.0,)]


def test_verify_rejects_placeholder_fills_but_allows_real_imputation():
    before = frame(port=["S", "C", None, "S", None, "Q"])
    unknown = before.assign(port=before["port"].fillna("Unknown"))
    r = verify(before, unknown, "missing", "port")
    assert r.hard["placeholder_fill"] == "fail: 2 missing values in port filled with the placeholder 'Unknown'"
    assert r.score == 0.0
    mode = before.assign(port=before["port"].fillna("S"))  # the most frequent value is a real imputation
    assert verify(before, mode, "missing", "port").hard["placeholder_fill"] == "pass"


def test_reviewer_concerns_alone_do_not_block_a_commit():
    # The loop passes review_ok = not changed_something_it_shouldnt; concerns don't enter it.
    assert gate.decide([0.9, 0.85], 1.0, True, 10, 1000).gate == "commit"
    assert gate.decide([0.9, 0.85], 1.0, False, 10, 1000).gate == "flag"  # "changed something it shouldn't"


def test_cleaner_prompts_carry_nothing_from_the_sample_dataset():
    # CLAUDE.md Rule 4: no tuning to Titanic. The propose prompt's example label was "Median by
    # title in name", and live runs proposed exactly that as a candidate.
    import re
    from pathlib import Path

    from sherlock.cleaning import prompts

    header = (Path(__file__).parents[1] / "samples" / "titanic3.csv").read_text(encoding="utf-8").splitlines()[0]
    columns = {c.strip('"').lower() for c in header.split(",")} - {"name", "age", "sex"}  # plain English words
    text = "\n".join([prompts.SYSTEM, prompts.DIAGNOSE, prompts.PROPOSE, prompts.CRITIC, prompts.HELPERS]).lower()
    found = {w for w in columns | {"titanic", "passenger", "title in name"} if re.search(rf"\b{re.escape(w)}\b", text)}
    assert not found


def test_cleaner_prompts_keep_data_inside_one_data_block():
    # Review Day 2 M7 (TRD §3.5): column names sat outside <data>, and a value holding "</data>" closed the block.
    import re

    from sherlock.cleaning import prompts
    from sherlock.cleaning.loop import _json, _safe

    data_fields = {"column", "columns", "column_card", "samples", "examples", "details", "decisions", "cause",
                   "approaches", "dtypes", "label", "code", "effect", "changes", "checks", "instruction"}
    for template in (prompts.DIAGNOSE, prompts.PROPOSE, prompts.CRITIC):
        assert template.count("<data>") == 1 and template.count("</data>") == 1
        inside = template.split("<data>")[1].split("</data>")[0]
        outside = template.replace(inside, "")
        assert not (set(re.findall(r"{(\w+)}", outside)) & data_fields)
    assert "</data>" not in _safe('col</data>"') and "</data>" not in _json(["x</data>"])
    for template in (prompts.DIAGNOSE, prompts.PROPOSE, prompts.CRITIC):  # the user's words: inside the block
        assert "{instruction}" in template.split("<data>")[1].split("</data>")[0]
    # A step the user added names no column outside the block: its issue line is a fixed phrase.
    from sherlock.cleaning.loop import USER_ISSUE_LINE, issue_line
    assert issue_line({"user": True, "detector": "user_request", "column": "x</data>", "count": 0}) == USER_ISSUE_LINE


def test_verify_fails_a_step_that_quarantines_far_more_rows_than_its_issue():
    # Review Day 3 H1: a NaN comparison in the model's mask quarantined 78% of the rows for a 4-row issue.
    before = frame(port=["S"] * 40 + [None] * 4, cabin=[None] * 30 + ["C1"] * 14)
    everything = quarantine_rows(before, before["cabin"].isna() | before["port"].isna(), "fd: port")
    r = verify(before, everything, "missing", "port")
    assert r.issue_before == 4 and r.quarantined == 34
    assert r.hard["quarantine_scope"] == "fail: 34 rows quarantined for an issue in 4" and r.score == 0.0
    just_those = quarantine_rows(before, before["port"].isna(), "fd: port")
    assert verify(before, just_those, "missing", "port").hard["quarantine_scope"] == "pass"


# --- the cleaning plan (PRD CLEAN-8a) ------------------------------------------------------------------


def card_with(issues, columns=("fare", "age", "name", "ticket", "boat"), ids=("ticket",), leaking=("boat",)):
    full = []
    for n, (detector, column, count, severity) in enumerate(issues):
        full.append({"id": f"iss_{n}", "detector": detector, "column": column, "count": count, "severity": severity,
                     "proposal": f"fix {detector}", "examples": list(range(count))[:9], "details": {}})
    return {"version": 3, "issues": full, "columns": [{"name": c} for c in columns], "id_columns": list(ids),
            "leakage_candidates": [{"column": c, "target": "survived", "reason": "x"} for c in leaking]}


def test_plan_diagnose_groups_dedupes_and_marks_kept_columns():
    from sherlock.cleaning import plan

    card = card_with([("missing", "age", 263, 0.1), ("duplicates", None, 3, 0.05), ("duplicates", None, 9, 0.2),
                      ("outliers", "fare", 40, 0.01), ("leakage", "boat", 500, 0.4), ("id_candidates", "ticket", 900, 0.2),
                      ("whitespace_case", "ticket", 12, 0.02), ("brand_new_check", "name", 2, 0.01)])
    items = plan.diagnose(card)
    by_key = {i["key"]: i for i in items}
    assert len(items) == 7  # the two duplicates findings share a key
    assert by_key["duplicates|None"]["count"] == 9  # the most severe one, the one the loop attempts
    assert by_key["missing|age"]["module"] == "missing" and by_key["missing|age"]["ticked"] and by_key["missing|age"]["change"]
    assert by_key["outliers|fare"]["module"] == "outliers" and by_key["brand_new_check|name"]["module"] == "other"
    assert len(by_key["missing|age"]["examples"]) == 5
    kept = {k: i for k, i in by_key.items() if i["module"] == "kept"}
    assert set(kept) == {"leakage|boat", "id_candidates|ticket", "whitespace_case|ticket"}
    assert all(not i["ticked"] and not i["change"] for i in kept.values())
    assert kept["whitespace_case|ticket"]["reason"] == "ticket looks like an ID column, so it is left as is"
    assert kept["leakage|boat"]["reason"].startswith("Records the outcome")
    assert all(i["source"] == "sherlock" and i["instruction"] is None and i["id"].startswith("pit_") for i in items)


def test_plan_merge_keeps_ticks_by_key_and_ticks_new_fixes():
    from sherlock.cleaning import plan

    old = plan.diagnose(card_with([("missing", "age", 263, 0.1), ("outliers", "fare", 40, 0.01), ("sentinels", "name", 4, 0.02)]))
    old, _ = plan.apply_ops(old, [{"op": "untick", "item_id": next(i["id"] for i in old if i["key"] == "outliers|fare")}])
    items, notes = plan.merge(old, card_with([("missing", "age", 250, 0.1), ("outliers", "fare", 41, 0.01),
                                              ("mojibake", "name", 3, 0.03)]))
    by_key = {i["key"]: i for i in items}
    assert set(by_key) == {"missing|age", "outliers|fare", "mojibake|name"}
    assert not by_key["outliers|fare"]["ticked"] and by_key["outliers|fare"]["count"] == 41
    assert by_key["mojibake|name"]["ticked"]
    assert by_key["missing|age"]["id"] == next(i["id"] for i in old if i["key"] == "missing|age")  # same item
    assert notes == ["1 fix no longer needed: placeholder values in name.", "1 new fix found, ticked."]
    order = [i["module"] for i in items]
    assert order == sorted(order, key=list(plan.MODULES).index)


def test_plan_ops_tick_untick_modules_and_refusals():
    from sherlock.cleaning import plan

    items = plan.diagnose(card_with([("outliers", "fare", 40, 0.01), ("outliers", "age", 4, 0.01), ("missing", "age", 9, 0.1),
                                     ("leakage", "boat", 500, 0.4)]))
    out, summary = plan.apply_ops(items, [{"op": "untick_module", "module": "outliers"}])
    assert summary == "Unticked 2 fixes: outliers in fare, outliers in age."
    assert [i["ticked"] for i in out if i["module"] == "outliers"] == [False, False]
    assert all(i["ticked"] for i in items if i["module"] == "outliers")  # the input isn't changed
    age = next(i for i in out if i["key"] == "outliers|age")
    out, summary = plan.apply_ops(out, [{"op": "tick", "item_id": age["id"]}, {"op": "tick", "item_id": age["id"]}])
    assert summary == "Ticked 1 fix: outliers in age."
    assert plan.apply_ops(out, [{"op": "tick", "item_id": age["id"]}])[1] == "The plan already said that, so nothing changed."
    assert plan.run_params(out)["skip_keys"] == ["outliers|fare"]
    boat = next(i for i in out if i["key"] == "leakage|boat")
    for bad, message in ([{"op": "tick", "item_id": "pit_nope"}], "There's no item"), \
                        ([{"op": "tick", "item_id": boat["id"]}], "marked, not changed"), \
                        ([{"op": "untick_module", "module": "kept"}], "no module"), \
                        ([{"op": "explode"}], "Unknown op"):
        with pytest.raises(plan.PlanError, match=message):
            plan.apply_ops(out, bad)


def test_plan_ops_rewrite_add_and_remove_steps():
    # PRD CLEAN-8b: a fix rewritten in plain words, a step of the user's own, and the refusals.
    from sherlock.cleaning import plan

    items = plan.diagnose(card_with([("missing", "age", 263, 0.1), ("leakage", "boat", 500, 0.4)]))
    age = next(i for i in items if i["key"] == "missing|age")
    columns = ["fare", "age", "name"]
    out, summary = plan.apply_ops(items, [
        {"op": "set_instruction", "item_id": age["id"], "instruction": "  Fill age   with the median by class  "},
        {"op": "add", "column": "name", "instruction": "Trim spaces in name"},
        {"op": "add", "column": None, "instruction": "Quarantine rows with no fare and no age"},
    ], columns)
    assert summary == "Rewrote missing values in age. Added 2 steps on name, the rows."
    by_key = {i["key"]: i for i in out}
    assert by_key["missing|age"]["instruction"] == "Fill age with the median by class"  # spaces collapsed
    assert by_key["missing|age"]["action"].startswith("fix missing")  # Sherlock's wording stays beside it
    mine = [i for i in out if i["key"] is None]
    assert [i["module"] for i in out][:2] == ["yours", "yours"]  # Your steps come first
    assert [(i["column"], i["source"], i["detector"], i["ticked"], i["change"]) for i in mine] == [
        ("name", "you", "user_request", True, True), (None, "you", "user_request", True, True)]
    run = plan.run_params(out)
    assert run["instructions"] == {"missing|age": "Fill age with the median by class"}
    assert [(u["column"], u["instruction"]) for u in run["user_steps"]] == [
        ("name", "Trim spaces in name"), (None, "Quarantine rows with no fare and no age")]

    out, summary = plan.apply_ops(out, [{"op": "set_instruction", "item_id": age["id"], "instruction": None},
                                        {"op": "remove", "item_id": mine[0]["id"]}], columns, source="chat")
    assert summary == "Put Sherlock's wording back on missing values in age. Removed your 1 step on name."
    assert next(i for i in out if i["key"] == "missing|age")["instruction"] is None and len(out) == len(items) + 1
    out, summary = plan.apply_ops(out, [{"op": "remove", "item_id": age["id"]}], columns)  # Sherlock's: unticked
    assert summary == "Unticked 1 fix: missing values in age." and any(i["key"] == "missing|age" for i in out)
    added, _ = plan.apply_ops(out, [{"op": "add", "column": "fare", "instruction": "Round fares"}], columns, source="chat")
    assert next(i for i in added if i["column"] == "fare")["source"] == "chat"

    boat = next(i for i in items if i["key"] == "leakage|boat")
    for bad, message in ([{"op": "add", "column": "ghost", "instruction": "x"}], "isn't a column"), \
                        ([{"op": "add", "column": "name", "instruction": "   "}], "can't be empty"), \
                        ([{"op": "add", "column": "name", "instruction": "x" * 501}], "under 500"), \
                        ([{"op": "set_instruction", "item_id": boat["id"], "instruction": "fill it"}], "marked, not changed"), \
                        ([{"op": "set_instruction", "item_id": mine[1]["id"], "instruction": None}], "remove it instead"):
        with pytest.raises(plan.PlanError, match=message):
            plan.apply_ops(out if "item_id" not in bad[0] or bad[0]["item_id"] != mine[1]["id"] else added, bad, columns)


def test_plan_merge_keeps_instructions_and_the_users_steps_while_their_column_exists():
    from sherlock.cleaning import plan

    old = plan.diagnose(card_with([("missing", "age", 263, 0.1)]))
    old, _ = plan.apply_ops(old, [{"op": "set_instruction", "item_id": old[0]["id"], "instruction": "Median by class"},
                                  {"op": "add", "column": "name", "instruction": "Trim spaces"},
                                  {"op": "add", "column": "cabin", "instruction": "Keep the deck letter"},
                                  {"op": "add", "column": None, "instruction": "Quarantine empty rows"}],
                            ["age", "name", "cabin"])
    items, notes = plan.merge(old, card_with([("missing", "age", 250, 0.1)], columns=("age", "name")))
    assert next(i for i in items if i["key"] == "missing|age")["instruction"] == "Median by class"
    assert [(i["column"], i["instruction"]) for i in items if i["key"] is None] == [("name", "Trim spaces"), (None, "Quarantine empty rows")]
    assert notes == ["Dropped your step on cabin: the column is no longer in the file."]


def test_gate_flags_a_requested_step_instead_of_skipping_it():
    low = gate.decide([0.4, 0.1], 0.5, False, 10, 1000)
    assert low.gate == "skip" and low.reason == "low confidence (0.34)"
    kept = gate.decide([0.4, 0.1], 0.5, False, 10, 1000, requested=True)
    assert kept.gate == "flag" and kept.reason == "low confidence (0.34); kept because you asked for it"
    assert gate.decide([0.0], 1.0, True, 0, 1000, requested=True).gate == "skip"  # nothing passed the hard checks
    assert gate.decide([0.95, 0.9], 1.0, True, 10, 1000, requested=True).gate == "commit"


def test_a_users_step_may_quarantine_at_most_a_fifth_of_the_rows():
    # A user's step has no detector, so the issue-count cap can't apply; without this one a bad mask
    # could hide most of the file (Day 3: 1,020 of 1,309 rows for a 4-row issue).
    before = frame(city=["a"] * 100)
    too_many = quarantine_rows(before, before["_row_id"] <= 21, "your step")
    r = verify(before, too_many, None, "city")
    assert r.hard["quarantine_scope"] == "fail: quarantines more than a fifth of the rows" and r.score == 0.0
    assert "resolved" not in r.soft  # no detector to re-run
    fine = quarantine_rows(before, before["_row_id"] <= 20, "your step")
    assert verify(before, fine, None, "city").hard["quarantine_scope"] == "pass"


# --- the cleaning log's line (TRD §7.2, BACKLOG D3 M2) -----------------------------------------


def test_the_log_line_takes_its_numbers_from_the_verifier_report():
    from sherlock.cleaning.verifiers import effect_line

    before = frame(age=[None] * 263 + ["x"] * 4 + [30.0] * 33)
    filled = before.assign(age=[30.0] * 263 + [None] * 4 + [30.0] * 33)
    after = quarantine_rows(filled, before["age"].eq("x"), "parse: age")
    r = verify(before, after, "missing", "age")
    line = effect_line(r, "missing values")
    assert line == f"Changed {r.cells_changed:,} cells, quarantined 4 rows; {r.issue_before:,} → {r.issue_after:,} missing values"
    numbers = [int(n.replace(",", "")) for n in re.findall(r"[\d,]+\d|\d", line)]
    assert numbers == [r.cells_changed, r.quarantined, r.issue_before, r.issue_after]
    one = verify(frame(a=["x ", "y"]), frame(a=["x", "y"]), None, "a")
    assert effect_line(one, None) == "Changed 1 cell"  # a user's step: no detector count
    only_rows = verify(before, quarantine_rows(before, before["age"].eq("x"), "bad"), None, "age")
    assert effect_line(only_rows, None) == "Quarantined 4 rows"


def test_the_models_sentence_is_shown_only_without_digits():
    from sherlock.cleaning.loop import issue_words, prose, short_line

    assert prose("Fills each missing age from the passenger's group.") == "Fills each missing age from the passenger's group."
    assert prose("Fills 263 missing ages.") is None and prose("Parses dates as ISO 8601") is None
    assert prose("Fills twelve missing ages.") is None  # a number in words is a number too
    assert prose("  ") is None and prose(None) is None
    issue = {"detector": "missing", "column": "age", "count": 263}
    assert issue_words(issue) == "missing values" and short_line(issue) == "263 missing values"
    assert issue_words({"user": True, "instruction": "trim", "detector": "user_request"}) is None


# --- merge safety (plan 2.5) -------------------------------------------------------------------


def test_look_alike_categories_are_not_merged():
    from sherlock.cleaning.detectors import near_duplicate_categories
    from tests.test_detectors import frame as detector_frame

    regions = ["Region 1"] * 30 + ["Region 2"] * 30 + ["Regon 1"] * 2 + ["male "] * 2 + ["Male"] * 20
    out = canonicalize_categories(pd.Series(regions, dtype=object))
    assert out.value_counts().to_dict() == {"Region 1": 32, "Region 2": 30, "Male": 22}  # a typo and case still merge
    countries = pd.Series(["Austria"] * 10 + ["Australia"] * 10 + ["Austrlia"] * 1, dtype=object)
    merged = canonicalize_categories(countries, threshold=85)
    assert (merged == "Austria").sum() == 10  # both common: kept apart
    mapped = canonicalize_categories(pd.Series(["Region 2", "region 1", "Region 1"] * 5, dtype=object),
                                     mapping={"Region 2": "Region 1", "region 1": "Region 1"})
    assert mapped.tolist()[:3] == ["Region 2", "Region 1", "Region 1"]  # the model's unsafe entry is left out
    assert canonicalize_categories(pd.Series(["Region 01", "Region 1", "Region 1"]), mapping={"Region 01": "Region 1"}).tolist() == ["Region 1"] * 3

    finding = near_duplicate_categories.detect(detector_frame(r=["region 1"] * 10 + ["region 2"] * 10 + ["region 3"] * 9))
    assert finding == []  # "region 1"/"region 2" (87.5) no longer pair
    (typos,) = near_duplicate_categories.detect(detector_frame(c=["Southampton"] * 30 + ["Southmpton"] * 2 + ["Cherbourg"] * 20))
    assert typos.details["pairs"] == [["southmpton", "southampton"]]


def test_a_merge_of_look_alike_categories_fails_the_checks():
    before = frame(region=["Region 1"] * 10 + ["Region 2"] * 10 + [" region 1"] * 2)
    fixed = before.assign(region=["Region 1"] * 10 + ["Region 2"] * 10 + ["Region 1"] * 2)
    assert verify(before, fixed, "whitespace_case", "region").hard["merge_safety"] == "pass"
    merged = before.assign(region=["Region 1"] * 22)
    r = verify(before, merged, "near_duplicate_categories", "region")
    assert r.hard["merge_safety"] == "fail: merged 'Region 2' into 'Region 1', which differ only in their numbers"
    assert r.score == 0.0
    common = frame(country=["Austria"] * 10 + ["Australia"] * 10)
    r = verify(common, common.assign(country=["Australia"] * 20), "near_duplicate_categories", "country")
    assert r.hard["merge_safety"] == "fail: merged 'Austria' into 'Australia', which are both common"
    rare = frame(city=["Southampton"] * 30 + ["Southmpton"] * 1)
    assert verify(rare, rare.assign(city=["Southampton"] * 31), "near_duplicate_categories", "city").hard["merge_safety"] == "pass"


# --- output agreement (plan 2.4) ---------------------------------------------------------------


def test_candidates_that_value_the_same_cells_differently_disagree():
    from sherlock.cleaning.verifiers import compare

    before = frame(d=["03/04/2021", "05/06/2021", "11/12/2021", "07/08/2021"], n=["1", "2", "3", "4"])
    day_first = before.assign(d=parse_dates_smart(before["d"], order_hint="dmy"))
    month_first = before.assign(d=parse_dates_smart(before["d"], order_hint="mdy"))
    same_again = before.assign(d=pd.to_datetime(before["d"], format="%d/%m/%Y"))
    untouched = before.copy()
    c = compare(before, [day_first, month_first, same_again, untouched, None], best=0)
    assert c.disagreement == 1.0 and c.pair == (0, 1)
    assert c.examples == [("03/04/2021", "3 Apr 2021", "4 Mar 2021"), ("05/06/2021", "5 Jun 2021", "6 May 2021")]
    assert c.agreement == pytest.approx(2 / 5)  # itself and the same reading; not the other, the no-op or the failure
    assert gate.disagree(c.disagreement) == "the candidates disagree on 100% of the cells they both change"

    # Results that change the same cells to the same values agree, whatever their types.
    money = frame(x=["$1,200", "$5", "7", "$10"])
    one = money.assign(x=parse_numbers(money["x"]))
    other = money.assign(x=pd.Series([1200, 5, 7, 10], dtype="Int64"))
    agree = compare(money, [one, other], best=0)
    assert agree.disagreement == 0.0 and agree.agreement == 1.0 and gate.disagree(0.0) is None
    # One cell valued apart in 200 both change: 0.5% is within the 1% that still agrees.
    many = frame(x=[f"${i}" for i in range(200)])
    a = many.assign(x=parse_numbers(many["x"]))
    b = a.assign(x=a["x"].where(a["_row_id"] != 5, -1.0))
    near = compare(many, [a, b], best=0)
    assert near.disagreement == pytest.approx(0.005) and gate.disagree(near.disagreement) is None
    assert near.agreement == 1.0
