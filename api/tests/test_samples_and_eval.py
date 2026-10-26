import pandas as pd
import pytest

from sherlock.eval import corruption, synthetic
from tests.test_jobs import wait_status

SAMPLES = corruption.SAMPLE.parent


@pytest.mark.usefixtures("run_jobs")
@pytest.mark.parametrize(("name", "options", "rows", "columns"), [
    ("sales_dated.csv", None, 5000, 8), ("wide_messy.csv", None, 800, 60), ("reviews_text.csv", None, 600, 6),
    # Its two preamble lines carry the same delimiters as the data, so the sniffer can't place the
    # header; the import preview's header-row control does (App Flow §3.2).
    ("broken_latin1.txt", '{"header_row": 3}', 150, 4),
])
def test_sample_files_import_and_profile(client, name, options, rows, columns):
    r = client.post("/api/v1/datasets", files={"file": (name, (SAMPLES / name).read_bytes(), "text/csv")},
                    data={"options": options} if options else None)
    assert r.status_code == 201, r.text
    ds = r.json()
    done = wait_status(client, ds["id"], "offer", "failed")
    assert done["status"] == "offer", done
    assert (done["row_count"], done["column_count"]) == (rows, columns)


def test_samples_are_seeded():
    pd.testing.assert_frame_equal(synthetic.sales(rows=50), synthetic.sales(rows=50))
    assert synthetic.broken_latin1() == synthetic.broken_latin1()


def test_benchmark_scoring():
    case = corruption.corrupt("t", pd.DataFrame({"x": [1.5, 2.5, 3.5, 4.5] * 5, "c": ["North", "South"] * 10}),
                              [("x", "money", 0.25), ("c", "case", 0.2)], seed=1)
    assert len(case.damage) == 9 and case.dirty.at[case.damage[0].row, "x"].startswith("$")

    def as_final(df):
        return df.assign(_row_id=range(1, len(df) + 1), _quarantine_reason=None)

    perfect = corruption.score(case, as_final(case.clean), 2, 1.0, "done")
    assert (perfect.recovered, perfect.harmed) == (9, 0)
    untouched = corruption.score(case, as_final(case.dirty), 0, 1.0, "done")
    assert untouched.recovered == 0 and untouched.harmed == 0
    harmful = as_final(case.clean)
    harmful.loc[harmful.index[~harmful.index.isin([d.row for d in case.damage])][:2], "c"] = "Nowhere"
    assert corruption.score(case, harmful, 1, 1.0, "done").harmed == 2
    assert "| t | 20 | 9 | 100.0% | 0.0% | 0.00% | 0.0% |" in perfect.row()  # recovered, wrong, harm, row loss


def test_benchmark_counts_wrong_guesses_and_keeps_ambiguous_text_unread():
    # A date left as "04/03/2021" isn't recovered (reading it would pick an order), and isn't wrong
    # either; the same date read in the other order is wrong (plan 2.6).
    assert not corruption.same("04/03/2021", "2021-04-03") and corruption.same("2021-04-03", "2021-04-03")
    assert corruption.same(pd.Timestamp("2021-04-03"), "2021-04-03") and corruption.same("22", 22.0)
    visits = synthetic.visits(rows=40)
    assert all(pd.Timestamp(d).day <= 12 and pd.Timestamp(d).day != pd.Timestamp(d).month for d in visits["visit_date"])
    case = corruption.corrupt("d", visits, [("visit_date", "mdy_text", 1.0)], seed=5)
    assert len(case.damage) == 40
    final = case.dirty.assign(_row_id=range(1, 41), _quarantine_reason=None)
    left = corruption.score(case, final, 0, 1.0, "done")
    assert (left.recovered, left.wrong, left.harmed) == (0, 0, 0)
    day_first = final.assign(visit_date=pd.to_datetime(case.dirty["visit_date"], format="%d/%m/%Y"))
    guessed = corruption.score(case, day_first, 1, 1.0, "done")
    assert (guessed.recovered, guessed.wrong) == (0, 40) and "| 0.0% | 100.0% | 0.00% |" in guessed.row()
    assert not corruption.changed(-999.0, "-999") and corruption.changed(pd.Timestamp("2021-03-04"), "04/03/2021")
    month_first = final.assign(visit_date=pd.to_datetime(case.dirty["visit_date"], format="%m/%d/%Y"))
    assert corruption.score(case, month_first, 1, 1.0, "done").recovered == 40


def test_lookalike_set_holds_common_categories_that_differ_on_purpose():
    df = synthetic.lookalikes(rows=600)
    shares = {c: df[c].value_counts(normalize=True) for c in ("plan", "region", "country")}
    assert set(shares["region"].index) == {"Region 1", "Region 2", "Region 3", "Region 4"}
    assert shares["country"]["Austria"] >= 0.05 and shares["country"]["Australia"] >= 0.05
    cases = {c.name: c for c in corruption.cases()}
    assert {"dates_dmy", "dates_mdy", "lookalikes"} <= set(cases)
    assert (cases["dates_dmy_picked"].date_order, cases["dates_mdy_picked"].date_order) == ("dmy", "mdy")
    assert cases["dates_dmy"].date_order is None
