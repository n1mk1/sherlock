"""The Cleaner gaps of the live test on 2026-10-26 (findings 5, 6, 18, 19 and 20), with recorded
replies: impossible values are quarantined whatever the diagnosis and the review say, a column of
prices isn't taken for an ID, step titles name their column once, the progress total holds still,
and a region with a letter left out ("Wst") merges into its neighbour as a flagged step. And the two
gaps the re-run found: a price column stored as text is parsed even when the propose reply is cut
off at its token cap, and no step title names its column twice ("... on units (units)")."""

from pathlib import Path

import pandas as pd
import pytest

from sherlock.cleaning import gate
from sherlock.cleaning.detectors import id_candidates, impossible_values, near_duplicate_categories
from sherlock.cleaning.helpers import _merge_refusal, canonicalize_categories
from sherlock.cleaning.helpers import parse_failures, parse_numbers, quarantine_rows
from sherlock.cleaning.detectors.impossible_values import RULE_LABEL
from sherlock.cleaning.loop import code_fix, queue, rule_candidate, rule_only, step_summary
from sherlock.cleaning.plan import never_change
from sherlock.cleaning.verifiers import Report
from sherlock.config import get_settings
from sherlock.profile.datacard import build_frame
from sherlock.profile.infer import measure_like
from tests.test_jobs import db_rows, events_of, upload, wait_for, wait_status

API = "/api/v1"
FIXTURES = Path(__file__).parent / "fixtures" / "llm" / "cleaner_gaps.json"
pytestmark = pytest.mark.usefixtures("run_jobs")

AGES = [str(20 + (i * 7) % 50) for i in range(40)] + ["-5", "130", "999"]
AGES_CSV = ("customer_id,customer_age,city\n" + "".join(
    f"C{100 + i},{a},{['Basel', 'Bern'][i % 2]}\n" for i, a in enumerate(AGES))).encode()
REGIONS = ["West"] * 12 + ["Wst"] * 8 + ["East"] * 12 + ["North"] * 10
REGIONS_CSV = ("shop_id,region,visits\n" + "".join(
    f"S{300 + i},{r},{3 + i % 4}\n" for i, r in enumerate(REGIONS))).encode()


def frame(**columns):
    n = max(len(v) for v in columns.values())
    df = pd.DataFrame({k: list(v) + [None] * (n - len(v)) for k, v in columns.items()})
    df.index = range(1, n + 1)
    return build_frame(df.astype(object).where(df.notna(), None), {})


@pytest.fixture(autouse=True)
def mocked_llm(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", str(FIXTURES))
    get_settings.cache_clear()


def clean(client, csv: bytes, name: str) -> tuple[dict, dict]:
    ds = wait_status(client, upload(client, csv, name)["id"], "offer", "failed")
    job = client.post(f"{API}/datasets/{ds['id']}/clean", json={}).json()
    wait_for(lambda: client.get(f"{API}/jobs/{job['id']}").json()["status"] in ("done", "failed", "cancelled"),
             timeout=90)  # a few sandbox runs: slow on a busy machine
    return ds, job


# --- 5: impossible values ------------------------------------------------------------------------

def test_impossible_values_carry_their_domain_rule():
    f = frame(customer_age=AGES, discount_pct=["5", "150"] * 10 + ["20"], visits=["-3"] + ["4"] * 20)
    found = {x.column: x for x in impossible_values.detect(f)}
    assert found["customer_age"].details == {"rule": "customer_age must be between 0 and 120", "low": 0, "high": 120}
    assert found["discount_pct"].details["high"] == 100 and found["discount_pct"].count == 10
    assert "visits" not in found  # no domain in the name, no rule


def test_the_rules_own_fix_quarantines_what_the_rule_names():
    issue = {"detector": "impossible_values", "column": "customer_age", "details": {"low": 0, "high": 120}}
    rule = rule_candidate(issue)
    assert rule.label == RULE_LABEL
    assert "(values < 0) | (values > 120)" in rule.code and "quarantine_rows(df, bad, 'impossible: customer_age')" in rule.code
    assert rule_candidate({**issue, "detector": "outliers"}) is None
    assert rule_candidate({**issue, "details": {}}) is None
    assert rule_only(Report(quarantined=3, cells_changed=0, issue_after=0))
    assert not rule_only(Report(quarantined=3, cells_changed=2, issue_after=0))


def test_a_columns_placeholders_go_before_its_domain_rule():
    # "-999" in an age is a placeholder: it becomes missing first, and the rule takes what is left.
    issues = [{"detector": "impossible_values", "column": "age", "severity": 0.14},
              {"detector": "missing", "column": "cabin", "severity": 0.1},
              {"detector": "sentinels", "column": "age", "severity": 0.05},
              {"detector": "sentinels", "column": "units", "severity": 0.02}]
    # By level first: placeholders and impossible values skew answers, missing values are worth a look.
    assert [(i["detector"], i["column"]) for i in queue(issues, {"columns": []})] == [
        ("sentinels", "age"), ("impossible_values", "age"), ("sentinels", "units"), ("missing", "cabin")]


def test_a_domain_rule_is_flagged_not_skipped():
    low = gate.decide([0.6], 0.5, False, 10, 1000, domain_rule=True)
    assert low.gate == "flag" and low.reason.endswith("kept because the values break the column's domain rule")
    assert gate.decide([0.6], 0.5, False, 10, 1000).gate == "skip"
    commit = gate.decide([1.0], 1.0, True, 10, 1000)
    over = gate.overrule(commit, "customer_age must be between 0 and 120")
    assert over.gate == "flag" and "(customer_age must be between 0 and 120)" in over.reason


def test_impossible_ages_are_quarantined_though_the_diagnosis_and_review_would_keep_them(client):
    # The recorded diagnosis says "leave as is", the model's one candidate clips the ages, and the
    # critic objects: the ages are still quarantined by the rule's own fix, committed with a flag.
    ds, job = clean(client, AGES_CSV, "customers.csv")
    report = client.get(f"{API}/datasets/{ds['id']}/report").json()
    (step,) = report["steps"]
    assert step["summary"] == "Quarantine impossible values (customer_age)"
    assert step["gate"] == "flag" and step["flag_reason"].startswith("the review objected, but every row it sets aside")
    assert step["impact"]["quarantined"] == 3 and step["impact"]["cells_changed"] == 0
    card = client.get(f"{API}/datasets/{ds['id']}/datacard").json()
    age = next(c for c in card["columns"] if c["name"] == "customer_age")
    assert card["quarantined"] == 3 and age["stats"]["max"] <= 120 and age["stats"]["min"] >= 0
    calls = db_rows("SELECT purpose FROM llm_calls WHERE job_id = ? ORDER BY id", job["id"])
    assert [c["purpose"] for c in calls] == ["diagnose", "propose", "critic"]
    # 19: the progress total is the issues expected at the start and doesn't grow.
    progress = [d for t, d in events_of(ds["id"]) if t == "job.progress" and d["job_id"] == job["id"]]
    assert {p["of"] for p in progress if p["of"]} == {2}  # impossible values, then outliers (settled by the first)


# --- 6: a price column isn't an ID ---------------------------------------------------------------

PRICES = [f"{10 + i * 1.37:.2f}" for i in range(40)] + ["$4.20", "$12.95", "n/a", "n/a"]


def test_mostly_unique_amounts_are_a_measure_not_an_id():
    f = frame(order_id=[f"O{i:04d}" for i in range(44)], unit_price=PRICES, ref=[str(1000 + i) for i in range(44)])
    price = f.columns["unit_price"]
    assert price.type != "id" and price.role == "measure"
    assert [x.column for x in id_candidates.detect(f)] == ["order_id", "ref"]  # whole numbers may be IDs
    assert f.columns["order_id"].role == "id"
    assert measure_like(pd.Series(["36.74", "$4.20", "1,250", "12%"])) and not measure_like(pd.Series(["1001", "00123", "A17"]))
    floats = frame(score=[f"{i / 7:.4f}" for i in range(30)])
    assert floats.columns["score"].type == "float" and id_candidates.detect(floats) == []


def test_an_id_flag_does_not_block_type_fixes():
    card = {"id_columns": ["unit_price"], "leakage_candidates": []}
    for detector in ("sentinels", "numbers_as_text"):
        assert never_change({"detector": detector, "column": "unit_price"}, card) is None
    assert never_change({"detector": "outliers", "column": "unit_price"}, card)[1] == "id_candidates"


def test_a_price_column_gets_its_type_fixes_planned(client):
    csv = ("order_id,unit_price,units\n" + "".join(f"O{i:04d},{p},{1 + i % 5}\n" for i, p in enumerate(PRICES))).encode()
    ds = wait_status(client, upload(client, csv, "orders.csv")["id"], "offer", "failed")
    card = client.get(f"{API}/datasets/{ds['id']}/datacard").json()
    assert "unit_price" not in card["id_columns"]
    found = {(i["detector"], i["column"]) for i in card["issues"]}
    assert {("sentinels", "unit_price"), ("numbers_as_text", "unit_price")} <= found
    assert ("id_candidates", "unit_price") not in found


# --- 18: step titles ---------------------------------------------------------------------------

def test_a_step_title_names_its_column_once():
    assert step_summary("Convert sentinels to NaN using strip_sentinels (units)", "units") == \
        "Convert sentinels to NaN using strip_sentinels (units)"
    assert step_summary("Parse numbers", "units") == "Parse numbers (units)"
    assert step_summary("Quarantine duplicate rows", None) == "Quarantine duplicate rows"
    # The live re-run's shape: the label names the column without brackets.
    assert step_summary("Parse numbers (handles commas, currency, %) on units", "units") == \
        "Parse numbers (handles commas, currency, %) on units"
    assert step_summary("Parse the Unit Price values", "unit_price") == "Parse the Unit Price values"
    assert step_summary("Parse unit_price as numbers", "unit_price") == "Parse unit_price as numbers"
    # A word that only contains the column's name doesn't count.
    assert step_summary("Strip unitsep characters", "units") == "Strip unitsep characters (units)"
    assert step_summary("Fill price_eur gaps", "price") == "Fill price_eur gaps (price)"


# --- numbers stored as text: the code's own parse ------------------------------------------------

PRICE_TEXT = [f"{10 + i * 1.37:.2f}" for i in range(40)] + ["$4.20", "$12.95", "$30.10"]


def test_numbers_as_text_has_a_code_fix():
    fix = code_fix({"detector": "numbers_as_text", "column": "unit_price"})
    assert fix.label == "Parse numbers"
    df = pd.DataFrame({"_row_id": [1, 2, 3, 4], "_quarantine_reason": [None] * 4,
                       "unit_price": ["36.74", "$4.20", "-1,250.50", "ask"]})
    scope = {"df": df, "pd": pd, "parse_numbers": parse_numbers, "parse_failures": parse_failures,
             "quarantine_rows": quarantine_rows}
    exec(fix.code, scope)
    out = scope["result"]
    assert out["unit_price"].tolist()[:3] == [36.74, 4.2, -1250.5]  # a minus sign is kept
    assert out["_quarantine_reason"].tolist() == [None, None, None, "unparsed: unit_price"]
    assert code_fix({"detector": "outliers", "column": "unit_price"}) is None
    assert code_fix({"detector": "numbers_as_text", "column": "x", "user": True}) is None


def test_a_price_column_is_parsed_though_the_propose_reply_is_cut_off(client):
    # The recorded diagnosis says "leave as is" and both propose attempts (6,000 tokens, then the
    # client's retry at twice the cap) come back cut off: the code's own parse is the step.
    csv = ("order_id,unit_price\n" + "".join(f"O{i:04d},{p}\n" for i, p in enumerate(PRICE_TEXT))).encode()
    ds, job = clean(client, csv, "orders.csv")
    report = client.get(f"{API}/datasets/{ds['id']}/report").json()
    (step,) = report["steps"]
    assert step["summary"] == "Parse numbers (unit_price)"
    assert step["gate"] in ("commit", "flag") and step["impact"]["quarantined"] == 0
    card = client.get(f"{API}/datasets/{ds['id']}/datacard").json()
    price = next(c for c in card["columns"] if c["name"] == "unit_price")
    assert price["type"] == "float" and price["role"] == "measure" and price["stats"]["min"] == 4.2
    calls = db_rows("SELECT purpose, ok, error FROM llm_calls WHERE job_id = ? ORDER BY id", job["id"])
    assert [c["purpose"] for c in calls] == ["diagnose", "propose", "propose", "critic"]
    assert all(not c["ok"] and "finish_reason length" in c["error"] for c in calls[1:3])


# --- 20: a letter left out ----------------------------------------------------------------------

def test_a_letter_left_out_is_a_typo_even_when_both_spellings_are_common():
    counts = {"west": 12, "wst": 8, "austria": 30, "australia": 30, "sale": 20, "sales": 20, "mr.": 40, "mrs.": 30}
    assert _merge_refusal("Wst", "West", counts, 100) is None
    assert _merge_refusal("Austria", "Australia", counts, 100) == "are both common"
    assert _merge_refusal("Sale", "Sales", counts, 100) == "are both common"  # a last letter: a word of its own
    assert _merge_refusal("Mr.", "Mrs.", counts, 100) == "are both common"  # too few letters
    f = frame(region=REGIONS)
    (finding,) = near_duplicate_categories.detect(f)
    assert finding.details["pairs"] == [["wst", "west"]] and finding.details["review_pairs"] == [["wst", "west"]]
    merged = canonicalize_categories(pd.Series(REGIONS), mapping={"Wst": "West"})
    assert set(merged) == {"West", "East", "North"}
    assert gate.review(gate.decide([1.0], 1.0, True, 8, 126), [["wst", "west"]]).reason == \
        "merges spellings that are both common (wst → west); check them"


def test_wst_merges_into_west_as_a_flagged_step(client):
    ds, job = clean(client, REGIONS_CSV, "shops.csv")
    report = client.get(f"{API}/datasets/{ds['id']}/report").json()
    (step,) = report["steps"]
    assert step["summary"] == "Merge the listed pairs (region)"  # the label's column isn't repeated
    assert step["gate"] == "flag" and step["flag_reason"].startswith("merges spellings that are both common")
    regions = {r["cells"]["region"] for r in client.get(f"{API}/datasets/{ds['id']}/rows", params={"limit": 100}).json()["rows"]}
    assert regions == {"West", "East", "North"}


def test_near_duplicates_have_a_code_fix():
    issue = {"detector": "near_duplicate_categories", "column": "product",
             "details": {"pairs": [["gzmo", "gizmo"], ["srocket", "sprocket"]]}}
    fix = code_fix(issue)
    assert fix.label == "Merge the listed pairs"
    df = pd.DataFrame({"_row_id": range(8), "_quarantine_reason": [None] * 8,
                       "product": ["Gizmo", "Gizmo", "Gzmo", "gzmo", "Sprocket", "Sprocket", "Srocket", None]})
    scope = {"df": df, "pd": pd, "canonicalize_categories": canonicalize_categories}
    exec(fix.code, scope)
    assert scope["result"]["product"].tolist() == ["Gizmo"] * 4 + ["Sprocket"] * 3 + [None]
    assert code_fix({**issue, "details": {}}) is None


def test_a_merge_code_can_make_beats_setting_the_rows_aside(monkeypatch, tmp_path):
    # The model's only fix quarantines the "Wst" rows; code's own merge of the detector's pairs fixes the
    # same cells in place, so it is scored too and wins on the cells it touches.
    import json

    from fastapi.testclient import TestClient

    from sherlock.main import create_app
    entries = [e for e in json.loads(FIXTURES.read_text(encoding="utf-8"))
               if not (e["purpose"] == "propose" and "Column: region" in e["match"])]
    entries.insert(0, {"purpose": "propose", "match": ["Column: region", "wst"], "content": {"candidates": [
        {"label": "Set the rare spelling aside (region)",
         "code": "result = quarantine_rows(df, df['region'] == 'Wst', 'typo: region')",
         "expected_effect": "Quarantines the rows with the rare spelling."}]}})
    fixture = tmp_path / "set_aside.json"
    fixture.write_text(json.dumps(entries), encoding="utf-8")
    monkeypatch.setenv("LLM_MOCK", str(fixture))
    get_settings.cache_clear()
    with TestClient(create_app()) as client:
        ds, job = clean(client, REGIONS_CSV, "shops.csv")
        report = client.get(f"{API}/datasets/{ds['id']}/report").json()
        rows = client.get(f"{API}/datasets/{ds['id']}/rows", params={"limit": 100}).json()["rows"]
    (step,) = report["steps"]
    assert step["summary"] == "Merge the listed pairs (region)" and step["impact"]["quarantined"] == 0
    assert {r["cells"]["region"] for r in rows} == {"West", "East", "North"}
