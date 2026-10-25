"""The dashboard builder (TRD §7.3): candidates from roles, scoring, curation with its fallback, and
the build job end to end on the sample."""

from pathlib import Path

import duckdb
import pytest

from sherlock.config import get_settings
from sherlock.dashboard import builder, candidates, scoring
from sherlock.dashboard.candidates import Candidate
from sherlock.db.connection import connect
from sherlock.jobs.clean import queue_build
from sherlock.llm.client import CallScope, LLMClient
from sherlock.llm.fixtures import FixtureTransport
from tests.test_jobs import db_rows, wait_for, wait_status

API = "/api/v1"
FIXTURE = Path(__file__).parent / "fixtures" / "llm" / "dashboard_curate.json"


def col(name, type_, role, distinct, missing=0.0, **extra):
    return {"name": name, "type": type_, "role": role, "distinct": distinct, "missing_pct": missing, **extra}


CARD = {
    "row_count": 6, "column_count": 6, "target_candidates": ["survived"],
    "columns": [
        col("pclass", "int", "dimension", 3), col("survived", "int", "target_like", 2), col("name", "id", "id", 6),
        col("ticket", "text", "dimension", 900), col("fare", "float", "measure", 6), col("blank", "empty", "empty", 0),
    ],
}


def test_candidates_follow_roles():
    cands = candidates.generate(CARD)
    kinds = {c.key: c.kind for c in cands}
    assert kinds["kpi:rows"] == "kpi_rows" and kinds["kpi:rate:survived"] == "kpi_rate"
    assert kinds["kpi:avg:fare"] == "kpi_measure"
    assert kinds["bar:rate:survived:pclass"] == "target_rate" and kinds["bar:avg:fare:pclass"] == "measure_by_dim"
    assert "table:top:name:fare" in kinds
    # High-cardinality text and empty columns are never charted; the target isn't its own category.
    assert not any("ticket" in k or "blank" in k or (k.endswith(":survived") and not k.startswith("kpi")) for k in kinds)
    assert all("{{rows}}" in c.sql for c in cands)
    assert {c.view for c in cands} <= {"bar", "line", "area", "kpi", "table", "ring", "pie"}


def test_binary_text_target_counts_its_positive_value():
    card = {**CARD, "target_candidates": ["churn"], "columns": [
        col("churn", "category", "target_like", 2, top_values=[{"value": "no", "count": 9}, {"value": "yes", "count": 3}])]}
    t = candidates.binary_target(card)
    assert t.positive == "churn = yes" and "= 'yes'" in t.indicator


def test_scoring_runs_queries_and_ranks():
    conn = duckdb.connect()
    conn.execute("""CREATE TABLE t AS SELECT * FROM (VALUES
        (1, NULL::VARCHAR, 1, 1, 'a', 'x', 80.0), (2, NULL, 1, 1, 'b', 'x', 90.0), (3, NULL, 2, 0, 'c', 'y', 20.0),
        (4, NULL, 2, 1, 'd', 'y', 25.0), (5, NULL, 3, 0, 'e', 'z', 8.0), (6, NULL, 3, 0, 'f', 'z', 7.0),
        (7, 'dup', 3, 1, 'g', 'z', 9.0)) v(_row_id, _quarantine_reason, pclass, survived, name, ticket, fare)""")
    scored = scoring.score(conn, CARD, candidates.generate(CARD))
    by_key = {c.key: c for c in scored}
    rate = by_key["bar:rate:survived:pclass"]
    assert rate.parts["variance"] > 0.5 and rate.point == {"kind": "bar", "key": "1"}
    assert rate.facts["top"] == {"key": "1", "value": 1.0} and rate.facts["bottom"]["key"] == "3"
    assert by_key["kpi:rows"].facts == {"value": 6}  # the quarantined row is left out
    assert scored == sorted(scored, key=lambda c: -c.score)
    assert scoring.kendall_tau([1, 2, 3, 4]) == 1.0 and scoring.kendall_tau([1, 1]) == 0.0


def cand(i, view="bar", score=0.5):
    return Candidate(f"c{i}", "kpi_measure" if view == "kpi" else "measure_by_dim", view,
                     "SELECT 1 FROM t WHERE {{rows}}", f"Template {i}", [], score=score,
                     facts={"elements": ["a", "b"]}, point={"kind": "bar", "key": "a"} if view != "kpi" else None)


def test_shortlist_reserves_kpis_and_fallback_takes_eight():
    scored = [cand(i, score=1 - i / 100) for i in range(20)] + [cand(90 + i, "kpi", 0.01) for i in range(4)]
    short = builder.shortlist(scored)
    assert len(short) == 14 and sum(c.view == "kpi" for c in short) == 3
    fb = builder.fallback(short)
    assert len(fb) == 8 and [c.view for c, _, _ in fb][:3] == ["kpi"] * 3
    assert all(title == c.title for c, title, _ in fb)


def test_curate_uses_titles_and_falls_back_per_title(client):
    short = [cand(i, "kpi" if i == 1 else "bar") for i in range(8)]
    llm = LLMClient(get_settings(), transport=FixtureTransport.load(FIXTURE))
    picks, by_model = builder.curate(llm, CallScope(), {"row_count": 1, "column_count": 1, "columns": []}, short)
    assert by_model is True and len(picks) == 6
    titles = [t for _, t, _ in picks]
    assert titles[0] == "Share who survived"  # the KPI moves first
    assert "Survival by sex" in titles and "Template 3" in titles  # "Top 3 fares" has digits
    sex = next(p for p in picks if p[1] == "Survival by sex")
    assert sex[2] == {"kind": "bar", "key": "a"}  # "female" isn't one of this candidate's elements
    families = next(p for p in picks if p[1] == "Families aboard")
    assert families[2] == {"kind": "bar", "key": "a"}


def test_curate_falls_back_when_the_model_is_unavailable(client):
    short = [cand(i) for i in range(10)]
    picks, by_model = builder.curate(LLMClient(get_settings()), CallScope(), {"row_count": 1, "column_count": 1, "columns": []}, short)
    assert by_model is False and len(picks) == 8


@pytest.mark.usefixtures("run_jobs")
def test_build_job_on_the_sample(client):
    ds = client.post(f"{API}/datasets/sample").json()
    wait_status(client, ds["id"], "offer")
    job = client.post(f"{API}/datasets/{ds['id']}/use-as-is").json()
    assert wait_status(client, ds["id"], "ready")["status"] == "ready"
    done = wait_for(lambda: (j := client.get(f"{API}/jobs/{job['id']}").json())["status"] == "done" and j)
    assert done["result"]["curated_by"] == "fallback" and done["result"]["widgets"] == 8

    out = client.get(f"{API}/datasets/{ds['id']}/widgets").json()
    widgets = out["widgets"]
    assert 6 <= len(widgets) <= 10 and all(w["created_by"] == "builder" and w["status"] == "ready" for w in widgets)
    views = [w["spec"]["view"]["type"] for w in widgets]
    assert views[:3] == ["kpi"] * 3 and "kpi" not in views[3:]
    assert [it["y"] for it in out["layout"]["lg"][:3]] == [0, 0, 0]
    for w in widgets:  # DASH-1: no widget errors on first render
        r = client.get(f"{API}/widgets/{w['id']}/data")
        assert r.status_code == 200 and r.json()["row_count"] > 0, (w["title"], r.text)
    assert any(w["title"] == "Rate of survived by sex" for w in widgets)

    # A second build (after a later whole-dataset clean, say) keeps the dashboard.
    db = connect(get_settings())
    second = queue_build(db, None, db_rows("SELECT user_id FROM datasets WHERE id = ?", ds["id"])[0][0], ds["id"])
    db.close()
    kept = wait_for(lambda: (j := client.get(f"{API}/jobs/{second['id']}").json())["status"] == "done" and j)
    assert kept["result"]["kept"] is True
    assert len(client.get(f"{API}/datasets/{ds['id']}/widgets").json()["widgets"]) == len(widgets)


@pytest.fixture
def mocked(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", str(FIXTURE))
    get_settings.cache_clear()


@pytest.mark.usefixtures("run_jobs")
def test_build_job_with_the_model(mocked, client):
    ds = client.post(f"{API}/datasets/sample").json()
    wait_status(client, ds["id"], "offer")
    client.post(f"{API}/datasets/{ds['id']}/use-as-is")
    wait_status(client, ds["id"], "ready")
    widgets = client.get(f"{API}/datasets/{ds['id']}/widgets").json()["widgets"]
    assert len(widgets) == 6
    assert "Survival by sex" in [w["title"] for w in widgets]
    calls = db_rows("SELECT purpose, role FROM llm_calls WHERE dataset_id = ?", ds["id"])
    assert [(c["purpose"], c["role"]) for c in calls] == [("curate", "medium")]
