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


@pytest.mark.parametrize(("scores", "clean", "changed", "expected"), [
    ([0.95, 0.9], True, 10, "commit"),          # 0.57 + 0.2 + 0.2
    ([0.95, 0.9], True, 300, "flag"),           # blast 0.3 ≥ 0.2
    ([0.8, 0.2], False, 10, "skip"),            # 0.48 + 0.1 + 0 = 0.58 → flag? see below
    ([0.0, 0.0], True, 0, "skip"),
    ([0.7, 0.65], False, 5, "flag"),            # 0.42 + 0.2 + 0 = 0.62
    ([0.5], False, 5, "skip"),                  # 0.30 + 0.2 = 0.50
])
def test_gate(scores, clean, changed, expected):
    d = gate.decide(scores, clean, changed, 1000)
    if scores == [0.8, 0.2]:
        assert d.gate == "flag" and d.confidence == pytest.approx(0.58)
    else:
        assert d.gate == expected
    assert d.confidence == pytest.approx(0.6 * max(scores) + 0.2 * gate.agreement(scores) + 0.2 * clean)


def test_quarantined_rows_count_as_all_their_cells_in_the_blast():
    # The live Titanic run (2026-10-25): a step quarantined 1,020 of 1,309 rows × 14 columns. Counted
    # as one cell each that was a 5.6% blast; it is 78% of the data.
    total = 1309 * 14
    affected = gate.cells_affected(0, 1020, 14, total)
    assert affected == 1020 * 14
    d = gate.decide([0.95, 0.9], True, affected, total)
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
    assert gate.decide([0.9, 0.85], True, 10, 1000).gate == "commit"
    assert gate.decide([0.9, 0.85], False, 10, 1000).gate == "flag"  # "changed something it shouldn't"


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
