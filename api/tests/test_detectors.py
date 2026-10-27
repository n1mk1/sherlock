"""Each detector on synthetic columns: it fires on the problem and stays quiet on clean data."""

import math
from statistics import NormalDist

import pandas as pd
import pytest

from sherlock.cleaning import registry
from sherlock.cleaning.detectors import (
    ambiguous_dates,
    cross_column,
    duplicates,
    functional_dependency,
    id_candidates,
    impossible_values,
    leakage,
    missing,
    mixed_types,
    mojibake,
    near_duplicate_categories,
    numbers_as_text,
    outliers,
    sentinels,
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


def test_weights_cover_the_sixteen_detectors():
    weights = {s.id: s.weight for s in registry.all() if s.source == "builtin" and s.id != "rule"}
    assert len(weights) == 16
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
