"""The Cleaner's output agreement and its date-order rule end to end, with recorded replies
(plan 2.4 and 2.6): candidates that value the same cells differently are skipped before the full
run, and dates that every value reads both ways are left as text with no model call."""

from pathlib import Path

import pytest

from sherlock.config import get_settings
from tests.test_jobs import db_rows, events_of, upload, wait_for, wait_status

API = "/api/v1"
FIXTURES = Path(__file__).parent / "fixtures" / "llm" / "cleaner_checks.json"
pytestmark = pytest.mark.usefixtures("run_jobs")

NAMES = ["mcdonald", "MCDONALD", "o'brien"] + ["McDonald"] * 20 + ["mcdonald"] * 2 + ["O'Brien"] * 12 + ["o'brien"] * 2
NAMES_CSV = ("customer_id,name,visits\n" + "".join(f"C{100 + i},{n},{i % 7}\n" for i, n in enumerate(NAMES))).encode()
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


def test_candidates_that_disagree_are_skipped_with_cells_shown_both_ways(client):
    ds, job = clean(client, NAMES_CSV, "names.csv")
    report = client.get(f"{API}/datasets/{ds['id']}/report").json()
    reason = {(s["detector"], s["column"]): s["reason"] for s in report["skipped"]}[("whitespace_case", "name")]
    # 7 cells both candidates change (4 McDonalds, 3 O'Briens); they value the 4 McDonalds apart.
    assert reason == ("Skipped: the candidates disagree on 57% of the cells they both change "
                      "(Title case vs Most frequent spelling: mcdonald → Mcdonald vs McDonald; MCDONALD → Mcdonald vs McDonald)")
    assert report["steps"] == []
    calls = db_rows("SELECT purpose FROM llm_calls WHERE job_id = ? ORDER BY id", job["id"])
    assert [c["purpose"] for c in calls] == ["diagnose", "propose"]  # no full run, no critic
    logs = [d for t, d in events_of(ds["id"]) if t == "job.log" and d["job_id"] == job["id"] and d.get("gate") == "skip"]
    assert any(e["text"] == reason and e["calls"]["count"] == 2 for e in logs)
    names = {r["cells"]["name"] for r in client.get(f"{API}/datasets/{ds['id']}/rows", params={"limit": 100}).json()["rows"]}
    assert {"mcdonald", "MCDONALD", "McDonald"} <= names  # nothing changed


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
