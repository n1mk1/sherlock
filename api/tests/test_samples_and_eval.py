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
    assert "| t | 20 | 9 | 100.0% | 0.00% | 0.0% |" in perfect.row()
