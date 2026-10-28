"""Each detector on synthetic columns: it fires on the problem and stays quiet on clean data."""

import math
from statistics import NormalDist

import pandas as pd
import pytest

from sherlock.cleaning import registry
from sherlock.cleaning.detectors import (
    ambiguous_dates,
    arithmetic_mismatch,
    blank_rows,
    conflicting_keys,
    cross_column,
    date_sequence,
    duplicates,
    functional_dependency,
    header_rows,
    id_candidates,
    impossible_values,
    label_conflicts,
    leakage,
    missing,
    mixed_types,
    mojibake,
    near_duplicate_categories,
    numbers_as_text,
    outliers,
    sentinels,
    summary_rows,
    time_gaps,
    unit_mixes,
    whitespace_case,
)
from sherlock.cleaning.detectors.numbers_as_text import clean_number
from sherlock.profile.datacard import build_frame


def frame(**columns):
    n = max(len(v) for v in columns.values())
    df = pd.DataFrame({k: list(v) + [None] * (n - len(v)) for k, v in columns.items()})
    df.index = range(1, n + 1)
    return build_frame(df.astype(object).where(df.notna(), None), {})


def counts(module, f, column=None):
    return {(x.column, x.details.get("kind")): x.count for x in module.detect(f)
            if column is None or x.column == column}


def test_weights_cover_the_built_in_detectors():
    weights = {s.id: s.weight for s in registry.all() if s.source == "builtin" and s.id != "rule"}
    assert len(weights) == 24
    assert weights["leakage"] == 1.0 and weights["id_candidates"] == 0.2


def test_missing_and_columns_missing_together():
    f = frame(a=["1", None, "3", None] * 5, b=["x", None, "y", None] * 5, c=[str(i) for i in range(20)])
    found = {x.column: x for x in missing.detect(f)}
    assert found["a"].count == 10 and found["a"].details["missing_with"] == ["b"]
    assert "c" not in found


def test_missing_flags_an_empty_column():
    f = frame(a=[None] * 5, b=["1"] * 5)
    (only,) = missing.detect(f)
    assert only.column == "a" and only.details["all_missing"]
    assert f.columns["a"].type == "empty" and f.columns["a"].role == "empty"


def test_mixed_types_numbers_with_words():
    values = [str(i) for i in range(1, 60)] + ["thirty", "unknown?x", "n.a. yet"]
    f = frame(age=values)
    (finding,) = mixed_types.detect(f)
    assert finding.count == 3 and "thirty" in finding.examples


def test_mixed_types_ignores_alphanumeric_codes():
    values = [str(10000 + i) for i in range(70)] + [f"PC {17000 + i}" for i in range(30)]
    assert mixed_types.detect(frame(ticket=values)) == []


def test_sentinels_text_and_numbers():
    values = [str(20 + i % 40) for i in range(100)] + ["N/A", "null", "?", "  "] + ["-999", "-999"]
    (finding,) = sentinels.detect(frame(score=values))
    assert finding.count == 6


def test_a_single_999_among_similar_values_is_not_a_sentinel():
    values = [str(900 + i) for i in range(100)] + ["999"]
    assert sentinels.detect(frame(code=values)) == []


def test_whitespace_and_case_variants():
    values = ["Paris"] * 10 + ["paris", "PARIS", " Paris", "London"] + ["London"] * 5
    (finding,) = whitespace_case.detect(frame(city=values))
    assert finding.details == {"stray_whitespace": 1, "case_variants": 2}
    assert finding.count == 3


def test_near_duplicate_categories():
    values = ["New York"] * 20 + ["New Yrok"] * 2 + ["Boston"] * 15 + ["Chicago"] * 10
    (finding,) = near_duplicate_categories.detect(frame(city=values))
    assert finding.count == 2 and finding.details["pairs"] == [["new yrok", "new york"]]


def test_near_duplicate_pairs_never_join_two_typos():
    # "srocket" is close to the typo "sproket" too: it still goes to "sprocket", once.
    values = ["Sprocket"] * 30 + ["Sproket"] * 2 + ["Srocket"] + ["Widget"] * 30
    (finding,) = near_duplicate_categories.detect(frame(product=values))
    assert sorted(finding.details["pairs"]) == [["sproket", "sprocket"], ["srocket", "sprocket"]]
    assert finding.count == 3


def test_exact_and_near_duplicates():
    f = frame(a=["x", "x", "X ", "y"], b=["1", "1", "1", "2"])
    found = {x.details["kind"]: x for x in duplicates.detect(f)}
    assert found["exact"].count == 1 and found["exact"].examples == [2]
    assert found["near"].count == 1 and found["near"].examples == [3]


def test_impossible_values():
    f = frame(
        age=["30", "-2", "45", "130"] * 5,
        discount_pct=["10", "120", "5", "50"] * 5,
        joined=["2020-01-01", "2099-05-01", "1750-01-01", "2021-06-01"] * 5,
        temperature=["-5", "3", "-10", "1"] * 5,
    )
    found = counts(impossible_values, f)
    assert found == {("age", None): 10, ("discount_pct", None): 5, ("joined", None): 10}


def test_numbers_stored_as_text():
    values = ["$1,200", "€3,50", "1.234,56", "45%", "(300)", "12"] * 5
    (finding,) = numbers_as_text.detect(frame(price=values))
    assert finding.count == 25
    assert clean_number("$1,200") == 1200 and clean_number("1.234,56") == 1234.56
    assert clean_number("(300)") == -300 and clean_number("1 234 567") == 1234567
    assert clean_number("5 9") is None  # two numbers, not one


def test_ambiguous_and_mixed_dates():
    ambiguous = frame(d=["03/04/2026", "05/06/2026", "11/12/2025"] * 5)
    assert counts(ambiguous_dates, ambiguous) == {("d", "ambiguous"): 15}
    mixed = frame(d=["25/04/2026"] * 6 + ["04/25/2026"] * 2 + ["01/02/2026"])
    assert counts(ambiguous_dates, mixed) == {("d", "mixed"): 2}
    clear = frame(d=["25/04/2026", "13/01/2026", "02/02/2026"])
    assert ambiguous_dates.detect(clear) == []


def test_mojibake():
    values = ["CafÃ©", "Café", "naÃ¯ve", "plain"] * 3
    (finding,) = mojibake.detect(frame(word=values))
    assert finding.count == 6
    assert ["CafÃ©", "Café"] in finding.details["fixes"]


def test_unit_mixes():
    values = ["5 kg"] * 10 + ["11 lb"] * 3 + ["300 g"] * 2
    (finding,) = unit_mixes.detect(frame(weight=values))
    assert finding.count == 5 and finding.details["units"] == {"kg": 10, "lb": 3, "g": 2}


def test_cross_column_end_before_start():
    f = frame(start_date=["2026-01-01", "2026-03-01"] * 5, end_date=["2026-02-01", "2026-02-01"] * 5)
    (finding,) = cross_column.detect(f)
    assert (finding.column, finding.count) == ("end_date", 5)


def test_broken_functional_dependency():
    cities = (["Austin"] * 20 + ["Dallas"] * 20 + ["Boston"] * 20 + ["Salem"] * 20)
    states = (["TX"] * 20 + ["TX"] * 19 + ["CA"] + ["MA"] * 20 + ["MA"] * 20)
    findings = [x for x in functional_dependency.detect(frame(city=cities, state=states)) if x.column == "state"]
    assert len(findings) == 1 and findings[0].count == 1
    assert findings[0].details["determinant"] == "city"


def test_id_candidates():
    f = frame(order_id=[f"A{i:04d}" for i in range(50)], region=["N", "S"] * 25)
    assert [x.column for x in id_candidates.detect(f)] == ["order_id"]


def test_outliers_robust_and_log_scale():
    regular = [str(50 + (i % 30)) for i in range(100)] + ["5000"]
    (finding,) = outliers.detect(frame(amount=regular))
    assert finding.count == 1
    # Log-normal quantiles: very skewed in linear terms, normal on the log scale, so no outliers.
    skewed = [str(round(math.exp(NormalDist().inv_cdf((i + 0.5) / 200)), 4)) for i in range(200)]
    assert outliers.detect(frame(price=skewed)) == []


def test_leakage_by_values_and_by_presence():
    n = 200
    survived = ["1" if i % 3 == 0 else "0" for i in range(n)]
    boat = [str(i % 10 + 1) if s == "1" else None for i, s in enumerate(survived)]
    body = [str(i) if (s == "0" and i % 4 == 0) else None for i, s in enumerate(survived)]
    noise = [str(i % 7) for i in range(n)]
    f = frame(noise=noise, boat=boat, body=body, survived=survived)
    found = {x.column: x for x in leakage.detect(f)}
    assert set(found) == {"boat", "body"}
    assert found["boat"].details["target"] == "survived"
    assert found["body"].details["rule"] == "presence"


def test_run_all_sorts_by_severity():
    f = frame(a=["1", None] * 10, b=["x"] * 20)
    results = registry.run_all(f)
    assert results == sorted(results, key=lambda r: r[1], reverse=True)
    assert all(0 <= sev <= 1 for _, sev in results)


@pytest.mark.parametrize("values,expected", [
    (["1", "2", "3"] * 10, "int"),
    (["1.5", "2", "3.25"] * 10, "float"),
    (["true", "false", "yes"] * 10, "bool"),
    (["2026-01-02", "2025-12-31"] * 10, "date"),
    (["2026-01-02 10:15:00", "2025-12-31 08:00:00"] * 10, "datetime"),
    (["red", "blue", "green"] * 10, "category"),
    ([f"user{i}" for i in range(30)], "id"),
])
def test_type_inference(values, expected):
    assert frame(c=values).columns["c"].type == expected


def test_roles():
    f = frame(
        customer_id=[str(i) for i in range(40)],
        signup=["2026-01-01"] * 40,
        plan=["basic", "pro"] * 20,
        visits=[str(i % 5) for i in range(40)],
        spend=[str(i * 1.5) for i in range(40)],
        churn=["0", "1"] * 20,
    )
    roles = {n: c.role for n, c in f.columns.items()}
    assert roles == {"customer_id": "id", "signup": "time", "plan": "dimension", "visits": "dimension",
                     "spend": "measure", "churn": "target_like"}
    assert f.target_candidates == ["churn"]


def test_impossible_values_match_whole_words_of_the_name():
    from sherlock.cleaning.detectors.impossible_values import bounds

    assert bounds("customer_age") == (0, 120) and bounds("unitPrice") == (0, None) and bounds("units_sold") == (0, None)
    assert bounds("discount_pct") == (0, 100) and bounds("years_employed") == (0, None)
    # A word inside another word isn't one: no domain for these.
    assert bounds("account_balance") == bounds("average_temp") == bounds("country") == bounds("agent") == (None, None)


# --- batch 1 of the deeper layers (PRD §7.3.2, CLEAN-15) ---------------------------------------------


def test_header_rows_repeat_the_column_names():
    f = frame(item=["a", "item", "b", "Item "], price=["1", "price", "2", "PRICE"], note=["x", "y", "z", "w"])
    found = header_rows.detect(f)
    assert [(x.count, x.examples) for x in found] == [(2, [2, 4])]
    assert not header_rows.detect(frame(item=["a", "item"], price=["1", "2"], note=["x", "y"]))  # one match isn't a row


def test_blank_rows_are_empty_in_every_column():
    f = frame(a=["x", None, "y", "N/A"], b=["1", None, "2", None])
    assert [(x.count, x.examples) for x in blank_rows.detect(f)] == [(2, [2, 4])]  # a placeholder isn't a value
    assert not blank_rows.detect(frame(a=["x", None, "y"]))  # one column: those are missing values


def test_summary_rows_are_total_labels_as_a_whole_value():
    region = ["North", "South", "East", "Total", "West", "North subtotal", "Grand Total:", "Totally Fine"] + ["North"] * 12
    found = summary_rows.detect(frame(region=region, sales=[str(i) for i in range(20)]))
    assert [(x.count, x.examples) for x in found] == [(3, [4, 6, 7])]
    # A column where most values are such labels holds data, not summaries.
    assert not summary_rows.detect(frame(kind=["Total", "Subtotal", "Total", "x"], v=["1", "2", "3", "4"]))


def test_conflicting_keys_share_a_key_and_differ_elsewhere():
    ids = [f"C{i}" for i in range(20)] + ["C3", "C5"]
    city = [f"city{i}" for i in range(20)] + ["elsewhere", "city5"]
    found = conflicting_keys.detect(frame(customer_id=ids, city=city))
    assert [(x.count, x.details) for x in found] == [(2, {"key": "customer_id", "keys": 1})]  # C5 repeats exactly
    assert found[0].examples == [4, 21]
    # A column whose name doesn't say it identifies rows is never a key.
    assert not conflicting_keys.detect(frame(name=ids, city=city))


def test_arithmetic_mismatch_reads_the_rule_from_the_data():
    qty = [str(1 + i % 5) for i in range(40)]
    price = [f"{2 + i % 7}.50" for i in range(40)]
    total = [f"{int(q) * float(p):.2f}" for q, p in zip(qty, price)]
    total[7] = "999.00"
    found = arithmetic_mismatch.detect(frame(qty=qty, price=price, total=total))
    assert [(x.column, x.count, x.details["op"], x.details["parts"]) for x in found] == [("total", 1, "product", ["qty", "price"])]
    assert found[0].examples == ["999 ≠ 7.5"]  # 3 × 2.50
    net = [str(10 + i) for i in range(40)]
    tax = [str(i % 3) for i in range(40)]
    gross = [str(int(n) + int(t)) for n, t in zip(net, tax)]
    gross[2] = "0"
    found = arithmetic_mismatch.detect(frame(net_value=net, tax=tax, gross=gross))
    assert [(x.column, x.details["op"]) for x in found] == [("gross", "sum")]
    # No rule holds in almost every row: nothing to report.
    assert not arithmetic_mismatch.detect(frame(qty=qty, price=price, total=[str(i) for i in range(40)]))


def test_date_sequence_is_read_from_the_data_not_the_names():
    ordered = pd.date_range("2023-01-01", periods=60, freq="D")
    shipped = [d + pd.Timedelta(days=3) for d in ordered]
    shipped[10] = ordered[10] - pd.Timedelta(days=2)
    f = frame(ordered=[d.date().isoformat() for d in ordered], shipped=[d.date().isoformat() for d in shipped])
    found = date_sequence.detect(f)
    assert [(x.column, x.count, x.examples, x.details["earlier"]) for x in found] == [("shipped", 1, [11], "ordered")]
    # A pair the names already order is the cross-column detector's.
    f = frame(start_date=[d.date().isoformat() for d in ordered], end_date=[d.date().isoformat() for d in shipped])
    assert not date_sequence.detect(f)


def test_time_gaps_counts_missing_periods_and_is_never_changed():
    days = [d.date().isoformat() for d in pd.date_range("2024-01-01", periods=40, freq="D") if d.day not in (10, 11, 20)]
    found = time_gaps.detect(frame(day=days, reading=[str(i) for i in range(len(days))]))
    assert [(x.column, x.count, x.examples, x.details) for x in found] == [
        ("day", 3, ["2024-01-10", "2024-01-11", "2024-01-20"], {"step": "day"})]
    months = [d.date().isoformat() for d in pd.date_range("2020-01-01", periods=30, freq="MS") if d.month != 6]
    found = time_gaps.detect(frame(month=months))
    assert [(x.count, x.examples, x.details["step"]) for x in found] == [(2, ["2020-06", "2021-06"], "month")]
    # Many rows a day is a log of events, not a series with gaps.
    log = [d.date().isoformat() for d in pd.date_range("2024-01-01", periods=30, freq="D") for _ in range(3)]
    assert not time_gaps.detect(frame(day=log))
    assert registry.get("time_gaps").never_change and registry.get("time_gaps").default_level is None


def test_label_conflicts_need_every_other_column_to_match():
    f = frame(customer=["a", "a", "b", "c"], plan=["x", "x", "y", "y"], churn=["yes", "no", "no", "yes"])
    assert [(x.count, x.examples, x.details) for x in label_conflicts.detect(f)] == [(2, [1, 2], {"target": "churn"})]
    # Rows that differ anywhere else are different records and may differ honestly.
    f = frame(customer=["a", "b", "c", "d"], plan=["x", "x", "y", "y"], churn=["yes", "no", "no", "yes"])
    assert not label_conflicts.detect(f)
