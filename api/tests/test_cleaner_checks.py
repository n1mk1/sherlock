"""The Cleaner's output agreement and its date-order rule end to end, with recorded replies
(plan 2.4 and 2.6): candidates that value the same cells differently are skipped before the full
run, case and spacing variants of one value don't count as different, and dates that every value
reads both ways are left as text with no model call."""

from pathlib import Path

import pytest

from sherlock.config import get_settings
from tests.test_jobs import db_rows, events_of, upload, wait_for, wait_status

API = "/api/v1"
FIXTURES = Path(__file__).parent / "fixtures" / "llm" / "cleaner_checks.json"
pytestmark = pytest.mark.usefixtures("run_jobs")

NAMES = ["mcdonald", "MCDONALD", "o'brien"] + ["McDonald"] * 20 + ["mcdonald"] * 2 + ["O'Brien"] * 12 + ["o'brien"] * 2
NAMES_CSV = ("customer_id,name,visits\n" + "".join(f"C{100 + i},{n},{i % 7}\n" for i, n in enumerate(NAMES))).encode()
AMOUNTS = ["1,250", "2,500", "3,750", "4,125", "5,600", "6,075"] * 6
AMOUNTS_CSV = ("order_id,amount,units\n" + "".join(f"O{900 + i},\"{a}\",{1 + i % 5}\n" for i, a in enumerate(AMOUNTS))).encode()
DATES = ["03/04/2021", "05/06/2021", "11/12/2021", "07/08/2022", "01/02/2023", "09/10/2022", "02/03/2021",
         "04/05/2022", "06/07/2023", "08/09/2021", "10/11/2022", "12/01/2023"] * 3
DATES_CSV = ("visit_id,visit_date,clinic,minutes\n" + "".join(
    f"V{500 + i},{d},{['Riverside', 'Lakeview'][(i // 12) % 2]},{15 + (i * 7) % 40}\n" for i, d in enumerate(DATES))).encode()


@pytest.fixture(autouse=True)
def mocked_llm(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", str(FIXTURES))
    get_settings.cache_clear()


def clean(client, csv: bytes, name: str) -> tuple[dict, dict]:
    ds = wait_status(client, upload(client, csv, name)["id"], "offer", "failed")
    job = client.post(f"{API}/datasets/{ds['id']}/clean", json={}).json()
    wait_for(lambda: client.get(f"{API}/jobs/{job['id']}").json()["status"] in ("done", "failed", "cancelled"))
    return ds, job


def test_case_variants_are_one_value_and_the_conservative_candidate_wins(client):
    # "Title case" and "Most frequent spelling" differ only in case ("Mcdonald" vs "McDonald"): one
    # value spelled two ways, so they agree; on equal scores the candidate that changes fewer cells
    # wins, and the most frequent spelling keeps "McDonald".
    ds, job = clean(client, NAMES_CSV, "names.csv")
    report = client.get(f"{API}/datasets/{ds['id']}/report").json()
    assert [s["summary"] for s in report["steps"]] == ["Most frequent spelling (name)"]
    calls = db_rows("SELECT purpose FROM llm_calls WHERE job_id = ? ORDER BY id", job["id"])
    assert [c["purpose"] for c in calls] == ["diagnose", "propose", "critic"]
    names = {r["cells"]["name"] for r in client.get(f"{API}/datasets/{ds['id']}/rows", params={"limit": 100}).json()["rows"]}
    assert names == {"McDonald", "O'Brien"}


def test_candidates_that_disagree_are_skipped_with_cells_shown_both_ways(client):
    ds, job = clean(client, AMOUNTS_CSV, "amounts.csv")
    report = client.get(f"{API}/datasets/{ds['id']}/report").json()
    reason = {(s["detector"], s["column"]): s["reason"] for s in report["skipped"]}[("numbers_as_text", "amount")]
    assert reason == ("Skipped: the candidates disagree on 100% of the cells they both change "
                      "(Thousands separator vs Decimal comma: 1,250 → 1250 vs 1.25; 2,500 → 2500 vs 2.5)")
    assert report["steps"] == []
    calls = db_rows("SELECT purpose FROM llm_calls WHERE job_id = ? ORDER BY id", job["id"])
    assert [c["purpose"] for c in calls] == ["diagnose", "propose"]  # no full run, no critic
    logs = [d for t, d in events_of(ds["id"]) if t == "job.log" and d["job_id"] == job["id"] and d.get("gate") == "skip"]
    assert any(e["text"] == reason and e["calls"]["count"] == 2 for e in logs)
    amounts = {r["cells"]["amount"] for r in client.get(f"{API}/datasets/{ds['id']}/rows", params={"limit": 100}).json()["rows"]}
    assert "1,250" in amounts  # nothing changed


def test_dates_that_read_both_ways_stay_text_and_cost_no_model_call(client):
    ds, job = clean(client, DATES_CSV, "visits.csv")
    card = client.get(f"{API}/datasets/{ds['id']}/datacard").json()
    assert next(c for c in card["columns"] if c["name"] == "visit_date")["type"] != "date"  # the import guessed no order
    report = client.get(f"{API}/datasets/{ds['id']}/report").json()
    reason = {(s["detector"], s["column"]): s["reason"] for s in report["skipped"]}[("ambiguous_dates", "visit_date")]
    assert reason.startswith("Left as text: every date reads both ways (03/04/2021 is 3 Apr 2021 or 4 Mar 2021; "
                             "05/06/2021 is 5 Jun 2021 or 6 May 2021)")
    assert db_rows("SELECT count(*) FROM llm_calls WHERE job_id = ?", job["id"])[0][0] == 0
    assert report["attempted"] == 0  # like a column that's never changed, it doesn't use the budget
    assert not any(s["detector"] == "near_duplicate_categories" for s in report["skipped"])  # dates a digit apart don't pair


def test_the_benchmark_leaves_dates_that_read_both_ways_and_says_why(client):
    from sherlock.eval import corruption, synthetic

    case = corruption.corrupt("dates_mdy", synthetic.visits(rows=40), [("visit_date", "mdy_text", 1.0)], 5)
    score = corruption.run_case(client, case, timeout_s=120)
    assert (score.recovered, score.wrong, score.harmed, score.rows_out) == (0, 0, 0, 40)
    assert any(d == "ambiguous_dates" and why.startswith("Left as text: every date reads both ways")
               for _, d, why in score.skipped)


def test_the_user_picks_the_date_order_in_the_plan_and_no_vote_runs(client):
    ds = wait_status(client, upload(client, DATES_CSV, "visits.csv")["id"], "offer", "failed")
    plan = client.post(f"{API}/datasets/{ds['id']}/clean/plan", json={}).json()
    item = next(i for i in plan["items"] if i["detector"] == "ambiguous_dates")
    assert item["needs_order"] is True and item["date_order"] is None
    assert item["both_ways"] == [
        {"value": "03/04/2021", "day_first": "3 Apr 2021", "month_first": "4 Mar 2021"},
        {"value": "05/06/2021", "day_first": "5 Jun 2021", "month_first": "6 May 2021"},
        {"value": "11/12/2021", "day_first": "11 Dec 2021", "month_first": "12 Nov 2021"}]
    bad = client.patch(f"{API}/clean-plans/{plan['id']}", json={"ops": [{"op": "set_date_order", "item_id": item["id"], "order": "ymd"}]})
    assert bad.status_code == 422
    other = next(i for i in plan["items"] if i["detector"] != "ambiguous_dates")
    refused = client.patch(f"{API}/clean-plans/{plan['id']}", json={"ops": [{"op": "set_date_order", "item_id": other["id"], "order": "dmy"}]})
    assert refused.status_code == 422 and "only ambiguous dates" in refused.json()["error"]["message"]
    r = client.patch(f"{API}/clean-plans/{plan['id']}", json={"ops": [{"op": "set_date_order", "item_id": item["id"], "order": "dmy"}]})
    assert r.status_code == 200 and r.json()["summary"] == "Set the date order of visit_date to day-first."
    job = client.post(f"{API}/datasets/{ds['id']}/clean", json={"plan_id": plan["id"]}).json()
    wait_for(lambda: client.get(f"{API}/jobs/{job['id']}").json()["status"] in ("done", "failed", "cancelled"))
    calls = [c["purpose"] for c in db_rows("SELECT purpose FROM llm_calls WHERE job_id = ? ORDER BY id", job["id"])]
    assert calls.count("diagnose") == 1 and calls[:3] == ["diagnose", "propose", "critic"]  # one diagnosis, no vote of three
    report = client.get(f"{API}/datasets/{ds['id']}/report").json()
    assert [s["summary"] for s in report["steps"]] == ["Parse day-first (visit_date)"]
    (mine,) = report["your_steps"]
    assert mine["outcome"] in ("fixed", "flagged") and mine["instruction"].startswith("Read every date in visit_date day-first")
    assert report["decisions"][0]["asked"] == mine["instruction"]
    card = client.get(f"{API}/datasets/{ds['id']}/datacard").json()
    assert next(c for c in card["columns"] if c["name"] == "visit_date")["type"] in ("date", "datetime")
    first = client.get(f"{API}/datasets/{ds['id']}/rows", params={"limit": 1}).json()["rows"][0]
    assert str(first["cells"]["visit_date"]).startswith("2021-04-03")  # 03/04/2021, day-first


def test_the_benchmark_set_with_a_picked_order_is_recovered(client):
    from sherlock.eval import corruption, synthetic

    for order, kind in (("dmy", "dmy_text"), ("mdy", "mdy_text")):
        case = corruption.picked(corruption.corrupt(f"dates_{order}_picked", synthetic.visits(rows=60), [("visit_date", kind, 1.0)], 4), order)
        score = corruption.run_case(client, case, timeout_s=120)
        assert (score.recovered, score.wrong, score.harmed, score.rows_out) == (60, 0, 0, 60), score


CITIES = ["Basel"] * 15 + [" Basel", "Basel  "] * 2 + ["Bern"] * 15 + ["Bern "] * 2
CITIES_CSV = ("shop_id,city,sales\n" + "".join(f"S{300 + i},\"{c}\",{10 + (i * 3) % 17}\n" for i, c in enumerate(CITIES))).encode()


def test_code_whose_line_breaks_came_escaped_still_runs(client):
    # The recorded reply's code is one line with a literal backslash-n, as Ultra sometimes writes it.
    ds, job = clean(client, CITIES_CSV, "shops.csv")
    report = client.get(f"{API}/datasets/{ds['id']}/report").json()
    assert [s["summary"] for s in report["steps"]] == ["Trim spaces (city)"]
    step = next(s for s in client.get(f"{API}/datasets/{ds['id']}/steps").json() if s["summary"] == "Trim spaces (city)")
    assert step["notebook_code"].startswith("result = df.copy()\nresult['city'] = ")
    cities = {r["cells"]["city"] for r in client.get(f"{API}/datasets/{ds['id']}/rows", params={"limit": 100}).json()["rows"]}
    assert cities == {"Basel", "Bern"}
