"""The headless Cleaner end to end on a small messy file, with recorded model replies."""

import json
from pathlib import Path

import pytest

from sherlock.config import get_settings
from tests.fixtures.messy import CSV
from tests.test_jobs import db_rows, events_of, upload, wait_for, wait_status

API = "/api/v1"
FIXTURES = Path(__file__).parent / "fixtures" / "llm" / "cleaner_messy.json"
pytestmark = pytest.mark.usefixtures("run_jobs")


@pytest.fixture(autouse=True)
def mocked_llm(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", str(FIXTURES))
    get_settings.cache_clear()


def finished(client, job_id):
    return wait_for(lambda: (j := client.get(f"{API}/jobs/{job_id}").json())["status"] in ("done", "failed", "cancelled") and j)


def offered(client, csv=CSV):
    ds = upload(client, csv, "messy.csv")
    return wait_status(client, ds["id"], "offer", "failed")


def test_clean_commits_steps_reports_and_builds(client):
    ds = offered(client)
    assert ds["status"] == "offer" and ds["current_version"] == 2  # the typing step typed age
    r = client.post(f"{API}/datasets/{ds['id']}/clean", json={})
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["kind"] == "clean"
    assert finished(client, job["id"])["status"] == "done"
    done = wait_status(client, ds["id"], "ready", "failed")
    assert done["status"] == "ready", done

    report = client.get(f"{API}/datasets/{ds['id']}/report").json()
    assert report["ended_by"] == "done" and report["job_id"] == job["id"]
    # Parsing the whole money column changes a quarter of this 4-column file's cells: over the 20%
    # blast limit, so it commits with a flag; the region fix commits outright.
    assert report["counts"]["fixed"] == 1 and report["counts"]["flagged"] == 1 and report["counts"]["rows_deleted"] == 0
    assert [s["summary"] for s in report["steps"]] == ["Parse money as numbers (amount)", "Normalize whitespace and case (region)"]
    skipped = {(s["detector"], s["column"]): s["reason"] for s in report["skipped"]}
    assert skipped[("id_candidates", "customer_id")].startswith("Looks like an ID column")
    assert skipped[("missing", "age")].startswith("Left as is")
    assert report["decisions"][0]["chosen"] == "Parse money as numbers"

    steps = client.get(f"{API}/datasets/{ds['id']}/steps").json()
    amount = next(s for s in steps if s["summary"].startswith("Parse money"))
    assert amount["created_by"] == "cleaner" and amount["gate"] == "flag" and amount["confidence"] >= 0.8
    assert amount["flag_reason"] == "changes more than a fifth of the data"
    assert amount["notebook_code"].endswith("df = result\n")
    assert amount["impact"]["quarantined"] == 1 and amount["impact"]["rows_in"] == amount["impact"]["rows_out"] == 120
    assert amount["verifiers"]["row_ledger"] == "pass"

    card = client.get(f"{API}/datasets/{ds['id']}/datacard").json()
    types = {c["name"]: c["type"] for c in card["columns"]}
    assert types["amount"] == "float" and card["quarantined"] == 1
    regions = {v["value"] for v in next(c for c in card["columns"] if c["name"] == "region")["top_values"]}
    assert regions == {"North", "South", "East"}
    flagged = client.get(f"{API}/datasets/{ds['id']}/rows", params={"view": "flagged"}).json()["rows"]
    assert [r["quarantine_reason"] for r in flagged if r["quarantined"]] == ["parse: amount"]
    assert flagged[0]["marks"]["amount"] == "flagged"  # every cell of a flagged step is marked

    # The live log: the typing step, then one entry per issue with candidates and the gate.
    logs = [d for t, d in events_of(ds["id"]) if t == "job.log" and d["job_id"] == job["id"]]
    assert logs[0]["column"] == "all columns" and "automatic step 1" in logs[0]["text"]
    flagged_entry = next(entry for entry in logs if entry.get("gate") == "flag")
    assert flagged_entry["candidates"] == [{"label": "Parse money as numbers", "chosen": True},
                                           {"label": "Coerce to numbers", "chosen": False}]
    assert flagged_entry["detail"].startswith("committed with a flag · step 2")
    committed = next(entry for entry in logs if entry.get("gate") == "commit" and entry.get("step_no") == 3)
    assert committed["detail"] == "committed · step 3" and committed["checks"]["row_ledger"] == "pass"
    assert [j["kind"] for j in client.get(f"{API}/jobs", params={"dataset_id": ds["id"]}).json()][:2] == [
        "build_dashboard", "clean"]
    calls = db_rows("SELECT purpose, role FROM llm_calls WHERE job_id = ?", job["id"])
    assert {(c["purpose"], c["role"]) for c in calls} == {("diagnose", "large"), ("propose", "large"), ("critic", "medium")}


def test_use_as_is_builds_on_the_typed_version(client):
    ds = offered(client)
    r = client.post(f"{API}/datasets/{ds['id']}/use-as-is")
    assert r.status_code == 201 and r.json()["kind"] == "build_dashboard"
    done = wait_status(client, ds["id"], "ready", "failed")
    assert done["status"] == "ready" and done["current_version"] == 2
    assert client.post(f"{API}/datasets/{ds['id']}/use-as-is").status_code == 409


def test_refusals(client):
    ds = offered(client)
    assert client.post(f"{API}/datasets/{ds['id']}/clean", json={"mode": "stepwise"}).status_code == 422
    assert client.post(f"{API}/datasets/{ds['id']}/clean", json={"scope": {"kind": "selection"}}).status_code == 422
    assert client.get(f"{API}/datasets/{ds['id']}/report").status_code == 404


def test_hand_edited_cells_are_kept_and_listed(client):
    ds = offered(client)
    # Edit one region by hand; the Cleaner must leave it as typed.
    r = client.post(f"{API}/datasets/{ds['id']}/edits", json={
        "base_version": ds["current_version"], "edits": [{"row_id": 3, "column": "region", "value": "  north  "}]})
    assert r.status_code == 201, r.text
    finished(client, client.post(f"{API}/datasets/{ds['id']}/clean", json={}).json()["id"])
    report = client.get(f"{API}/datasets/{ds['id']}/report").json()
    assert {"row_id": 3, "column": "region"} in report["hand_edited_skipped"]
    row = client.get(f"{API}/datasets/{ds['id']}/rows", params={"offset": 2, "limit": 1}).json()["rows"][0]
    assert row["_row_id"] == 3 and row["cells"]["region"] == "  north  "


@pytest.fixture
def no_model(monkeypatch, tmp_path, mocked_llm):
    empty = tmp_path / "none.json"
    empty.write_text("[]")
    monkeypatch.setenv("LLM_MOCK", str(empty))  # every call misses: the model is "unavailable"
    get_settings.cache_clear()


def test_unavailable_model_before_any_step_returns_to_the_offer(no_model, client):
    ds = offered(client)
    client.post(f"{API}/datasets/{ds['id']}/clean", json={})
    back = wait_for(lambda: (d := client.get(f"{API}/datasets/{ds['id']}").json())["status"] == "offer" and d.get("error") and d)
    assert back["error"].startswith("Cleaning stopped: ")
    job = client.get(f"{API}/jobs", params={"dataset_id": ds["id"]}).json()[0]
    assert job["kind"] == "clean" and job["status"] == "failed"
    assert client.get(f"{API}/datasets/{ds['id']}/report").json()["ended_by"] == "error"


def test_new_rows_scope_changes_only_those_rows(client):
    ds = offered(client)
    r = client.post(f"{API}/datasets/{ds['id']}/edits", json={
        "base_version": ds["current_version"], "run_cleaning_on_new_rows": True,
        "new_rows": [{"temp_id": "a", "cells": {"customer_id": "C9999", "region": " south", "amount": "$5", "age": "30"}}]})
    assert r.status_code == 201, r.text
    job = r.json()["clean_job"]
    assert job["kind"] == "clean"
    wait_for(lambda: client.get(f"{API}/jobs/{job['id']}").json()["status"] in ("done", "failed"))
    assert client.get(f"{API}/jobs/{job['id']}").json()["status"] == "done"
    page = client.get(f"{API}/datasets/{ds['id']}/rows", params={"limit": 500}).json()
    by_id = {r["_row_id"]: r for r in page["rows"]}
    new_id = r.json()["new_row_ids"]["a"]
    assert by_id[new_id]["cells"]["region"] == "South"
    assert any(row["cells"]["region"] in ("north ", " NORTH", "south") for row in page["rows"])  # old rows untouched
    # A scoped clean doesn't change the dataset's status.
    assert client.get(f"{API}/datasets/{ds['id']}").json()["status"] == "offer"
    assert json.loads(db_rows("SELECT params_json FROM jobs WHERE id = ?", job["id"])[0][0])["scope"]["kind"] == "new_rows"
