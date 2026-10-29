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


def test_clean_commits_steps_reports_and_ends_ready(client):
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
    # Each outcome line's numbers come from the step's full-data report, not the model's sentence,
    # which follows as a note without digits; the issue's model calls come from llm_calls (TRD §7.2).
    for entry in (flagged_entry, committed):
        v = next(s for s in steps if s["no"] == entry["step_no"])["verifiers"]
        assert str(v["cells_changed"]) in entry["text"] and f"{v['issue_before']} → {v['issue_after']}" in entry["text"]
        assert entry["note"] is None or not any(ch.isdigit() for ch in entry["note"])
        assert entry["calls"]["count"] == 3 and entry["calls"]["latency_ms"] >= 0  # diagnose, propose, critic
        assert entry["calls"]["models"] == [get_settings().model_large, get_settings().model_medium]
    assert flagged_entry["text"] == "Changed 120 cells, quarantined 1 row; 99 → 0 numbers stored as text"
    assert committed["text"] == "Changed 63 cells; 56 → 0 spacing or case variants"
    assert committed["note"] == "Merges spelling variants of each region."
    left = next(entry for entry in logs if entry.get("text", "").startswith("Left as is"))
    assert left["calls"]["count"] == 1  # the diagnosis alone
    # A whole clean ends `ready` by itself; it queues no other job (TRD §3.3).
    assert [j["kind"] for j in client.get(f"{API}/jobs", params={"dataset_id": ds["id"]}).json()] == ["clean", "profile"]
    statuses = [d["status"] for t, d in events_of(ds["id"]) if t == "dataset.status"]
    assert statuses[-2:] == ["cleaning", "ready"]
    calls = db_rows("SELECT purpose, role FROM llm_calls WHERE job_id = ?", job["id"])
    assert {(c["purpose"], c["role"]) for c in calls} == {("diagnose", "large"), ("propose", "large"), ("critic", "medium")}


def test_use_as_is_returns_the_dataset_ready_on_the_typed_version(client):
    ds = offered(client)
    r = client.post(f"{API}/datasets/{ds['id']}/use-as-is")
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["id"] == ds["id"] and done["status"] == "ready" and done["current_version"] == 2
    assert client.get(f"{API}/datasets/{ds['id']}").json()["status"] == "ready"
    assert [j["kind"] for j in client.get(f"{API}/jobs", params={"dataset_id": ds["id"]}).json()] == ["profile"]
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
    jobs = client.get(f"{API}/jobs", params={"dataset_id": ds["id"]}).json()
    assert [(j["kind"], j["status"]) for j in jobs] == [("clean", "failed"), ("profile", "done")]
    assert [d["status"] for t, d in events_of(ds["id"]) if t == "dataset.status"][-2:] == ["cleaning", "offer"]
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


@pytest.fixture
def slow_model(monkeypatch, mocked_llm):
    monkeypatch.setenv("LLM_MOCK", str(FIXTURES.parent / "cleaner_slow.json"))
    get_settings.cache_clear()


def test_stop_kills_the_running_worker_and_ends_ready(slow_model, client):
    import time

    ds = offered(client)
    job = client.post(f"{API}/datasets/{ds['id']}/clean", json={}).json()
    wait_for(lambda: any(e.get("detail") == "checking candidates"
                         for e in client.get(f"{API}/jobs/{job['id']}/log").json()["entries"]))
    time.sleep(1.5)  # the busy-loop candidate is running in the sandbox now
    stopped_at = time.monotonic()
    assert client.post(f"{API}/jobs/{job['id']}/cancel").status_code == 204
    done = finished(client, job["id"])
    assert done["status"] == "cancelled" and time.monotonic() - stopped_at < 10
    # Stop keeps the committed steps and the data is ready with them.
    ready = wait_status(client, ds["id"], "ready", "failed")
    assert ready["status"] == "ready" and ready["current_version"] >= ds["current_version"]
    assert sorted(s["no"] for s in client.get(f"{API}/datasets/{ds['id']}/steps").json()) == list(range(1, ready["current_version"]))
    assert client.get(f"{API}/datasets/{ds['id']}/report").json()["ended_by"] == "stopped"
    assert [j["kind"] for j in client.get(f"{API}/jobs", params={"dataset_id": ds["id"]}).json()] == ["clean", "profile"]


def test_after_upload_always_opens_the_plan_and_cleans_nothing(client):
    # Owner's report (2026-10-25): "always" used to clean every upload unattended, with nothing on
    # screen saying why. Now it makes a draft plan and stops at the offer; Discard shows the offer.
    assert client.put(f"{API}/me/settings", json={"after_upload": "always"}).status_code == 200
    ds = offered(client)
    assert ds["status"] == "offer" and ds["clean_plan_id"]
    plan = client.get(f"{API}/clean-plans/{ds['clean_plan_id']}").json()
    assert plan["source"] == "after_upload" and plan["status"] == "draft" and plan["version"] == ds["current_version"]
    assert [j["kind"] for j in client.get(f"{API}/jobs", params={"dataset_id": ds["id"]}).json()] == ["profile"]
    assert client.delete(f"{API}/clean-plans/{plan['id']}").status_code == 204
    back = client.get(f"{API}/datasets/{ds['id']}").json()
    assert back["status"] == "offer" and back["clean_plan_id"] is None


def test_after_upload_never_ends_ready_without_another_job(client):
    assert client.put(f"{API}/me/settings", json={"after_upload": "never"}).status_code == 200
    ds = upload(client, CSV, "messy.csv")
    assert wait_status(client, ds["id"], "ready", "failed")["status"] == "ready"
    assert [j["kind"] for j in client.get(f"{API}/jobs", params={"dataset_id": ds["id"]}).json()] == ["profile"]
    assert "offer" not in [d["status"] for t, d in events_of(ds["id"]) if t == "dataset.status"]


def item(plan, key):
    return next(i for i in plan["items"] if i["key"] == key)


def test_a_plan_round_trip_and_an_unticked_fix_is_skipped(client):
    ds = offered(client)
    r = client.post(f"{API}/datasets/{ds['id']}/clean/plan")
    assert r.status_code == 201, r.text
    plan = r.json()
    assert plan["status"] == "draft" and plan["source"] == "user" and plan["version"] == ds["current_version"]
    assert {i["key"] for i in plan["items"]} >= {"numbers_as_text|amount", "whitespace_case|region", "id_candidates|customer_id"}
    assert all(i["ticked"] == (i["sev"] != "check") for i in plan["items"] if i["change"])  # worth a look: unticked
    assert item(plan, "id_candidates|customer_id")["module"] == "kept" and not item(plan, "id_candidates|customer_id")["ticked"]
    assert client.get(f"{API}/datasets/{ds['id']}").json()["clean_plan_id"] == plan["id"]
    again = client.post(f"{API}/datasets/{ds['id']}/clean/plan")
    assert again.status_code == 200 and again.json()["id"] == plan["id"]  # one draft per dataset

    region = item(plan, "whitespace_case|region")
    r = client.patch(f"{API}/clean-plans/{plan['id']}", json={"ops": [{"op": "untick", "item_id": region["id"]}]})
    assert r.status_code == 200, r.text
    assert r.json()["summary"] == "Unticked 1 fix: spacing or case variants in region."
    assert not item(client.get(f"{API}/clean-plans/{plan['id']}").json(), "whitespace_case|region")["ticked"]
    bad = client.patch(f"{API}/clean-plans/{plan['id']}", json={"ops": [{"op": "tick", "item_id": "pit_nope"}]})
    assert bad.status_code == 422 and "no item" in bad.json()["error"]["message"]
    assert any(t == "plan.updated" and d["plan_id"] == plan["id"] for t, d in events_of(ds["id"]))

    r = client.post(f"{API}/datasets/{ds['id']}/clean", json={"plan_id": plan["id"]})
    assert r.status_code == 201, r.text
    job = r.json()
    started = client.get(f"{API}/clean-plans/{plan['id']}").json()
    assert started["status"] == "started" and started["job_id"] == job["id"]
    assert client.patch(f"{API}/clean-plans/{plan['id']}", json={"ops": [{"op": "tick", "item_id": region["id"]}]}).status_code == 409
    frozen = json.loads(db_rows("SELECT params_json FROM jobs WHERE id = ?", job["id"])[0][0])["plan"]
    assert frozen["id"] == plan["id"] and not item(frozen, "whitespace_case|region")["ticked"]
    assert finished(client, job["id"])["status"] == "done"
    assert wait_status(client, ds["id"], "ready", "failed")["clean_plan_id"] is None

    report = client.get(f"{API}/datasets/{ds['id']}/report").json()
    assert [s["summary"] for s in report["steps"]] == ["Parse money as numbers (amount)"]
    skipped = {(s["detector"], s["column"]): s["reason"] for s in report["skipped"]}
    assert skipped[("whitespace_case", "region")] == "You left this out of the plan"
    logs = [d for t, d in events_of(ds["id"]) if t == "job.log" and d["job_id"] == job["id"]]
    region_lines = [e for e in logs if e.get("column") == "region"]
    # No "checking candidates" line: the Cleaner logs that before its first model call on an issue.
    assert [e.get("detail") for e in region_lines] == ["not in your plan"]


def test_a_plan_made_before_a_hand_edit_is_merged_before_it_starts(client):
    ds = offered(client)
    plan = client.post(f"{API}/datasets/{ds['id']}/clean/plan").json()
    amount = item(plan, "numbers_as_text|amount")
    client.patch(f"{API}/clean-plans/{plan['id']}", json={"ops": [{"op": "untick", "item_id": amount["id"]}]})
    r = client.post(f"{API}/datasets/{ds['id']}/edits", json={
        "base_version": ds["current_version"], "edits": [{"row_id": 3, "column": "region", "value": "West"}]})
    assert r.status_code == 201, r.text
    stale = client.post(f"{API}/datasets/{ds['id']}/clean", json={"plan_id": plan["id"]})
    assert stale.status_code == 409
    merged = stale.json()["error"]["plan"]
    assert merged["version"] == ds["current_version"] + 1 and merged["notes"]
    assert not item(merged, "numbers_as_text|amount")["ticked"]  # the untick survives the merge
    assert item(merged, "numbers_as_text|amount")["id"] == amount["id"]
    assert client.get(f"{API}/clean-plans/{plan['id']}").json()["version"] == merged["version"]
    assert client.post(f"{API}/datasets/{ds['id']}/clean", json={"plan_id": plan["id"]}).status_code == 201


def test_start_shows_the_plan_again_when_its_ticks_changed_since_it_was_drawn(client):
    # The review can land between the screen's last read of the plan and Start: run only what the user saw.
    ds = offered(client)
    plan = client.post(f"{API}/datasets/{ds['id']}/clean/plan").json()
    seen = [i["id"] for i in plan["items"] if i["change"] and i["ticked"]]
    region = item(plan, "whitespace_case|region")
    client.patch(f"{API}/clean-plans/{plan['id']}", json={"ops": [{"op": "untick", "item_id": region["id"]}]})
    changed = client.post(f"{API}/datasets/{ds['id']}/clean", json={"plan_id": plan["id"], "ticked": seen})
    assert changed.status_code == 409 and "plan changed" in changed.json()["error"]["message"]
    assert not item(changed.json()["error"]["plan"], "whitespace_case|region")["ticked"]
    assert client.get(f"{API}/clean-plans/{plan['id']}").json()["status"] == "draft"
    now = [i for i in seen if i != region["id"]]
    assert client.post(f"{API}/datasets/{ds['id']}/clean", json={"plan_id": plan["id"], "ticked": now[::-1]}).status_code == 201


def test_a_plan_for_new_rows_keeps_its_scope_and_cleans_nothing_until_start(client):
    # PRD CLEAN-1: the new-rows toast's "Clean them" opens the plan for those rows instead of cleaning.
    ds = offered(client)
    r = client.post(f"{API}/datasets/{ds['id']}/clean/plan", json={"scope": {"kind": "new_rows", "row_ids": [7, 5, 7]}})
    assert r.status_code == 201, r.text
    plan = r.json()
    assert plan["scope"] == {"kind": "new_rows", "selection_id": None, "row_ids": [5, 7], "rows": 2}
    assert [j["kind"] for j in client.get(f"{API}/jobs", params={"dataset_id": ds["id"]}).json()] == ["profile"]
    # Clean with AI without a scope keeps the draft's; a whole-dataset scope clears it.
    again = client.post(f"{API}/datasets/{ds['id']}/clean/plan")
    assert again.status_code == 200 and again.json()["scope"]["rows"] == 2
    assert client.get(f"{API}/clean-plans/{plan['id']}").json()["scope"]["row_ids"] == [5, 7]
    cleared = client.post(f"{API}/datasets/{ds['id']}/clean/plan", json={"scope": {"kind": "all"}}).json()
    assert cleared["id"] == plan["id"] and cleared["scope"] is None
    bad = client.post(f"{API}/datasets/{ds['id']}/clean/plan", json={"scope": {"kind": "selection", "selection_id": "sel_nope"}})
    assert bad.status_code == 422 and "selection" in bad.json()["error"]["message"]
    assert sum(t == "plan.updated" and d["plan_id"] == plan["id"] for t, d in events_of(ds["id"])) == 2  # made, cleared


def test_plan_refusals(client):
    ds = upload(client, CSV, "messy.csv")
    assert client.post(f"{API}/datasets/{ds['id']}/clean/plan").status_code in (409, 201)  # 409 while profiling
    ds = wait_status(client, ds["id"], "offer", "failed")
    plan = client.post(f"{API}/datasets/{ds['id']}/clean/plan").json()
    ops = [{"op": "untick_module", "module": m} for m in {i["module"] for i in plan["items"] if i["change"]}]
    client.patch(f"{API}/clean-plans/{plan['id']}", json={"ops": ops})
    nothing = client.post(f"{API}/datasets/{ds['id']}/clean", json={"plan_id": plan["id"]})
    assert nothing.status_code == 422 and "Nothing in the plan is ticked" in nothing.json()["error"]["message"]
    assert client.post(f"{API}/datasets/{ds['id']}/clean", json={"plan_id": "pln_nope"}).status_code == 404
    assert client.get(f"{API}/clean-plans/pln_nope").status_code == 404
    # Clean it myself discards the draft.
    assert client.post(f"{API}/datasets/{ds['id']}/use-as-is").status_code == 200
    assert client.get(f"{API}/clean-plans/{plan['id']}").json()["status"] == "discarded"


def test_a_step_the_critic_rejects_is_skipped(monkeypatch, tmp_path):
    # Review Day 3 H2 (owner's decision, 2026-10-25): "changed something it shouldn't" used to cost
    # only 0.2 of the confidence, so such a step still committed with a flag. Now it's skipped.
    entries = json.loads(FIXTURES.read_text(encoding="utf-8"))
    entries.insert(0, {"purpose": "critic", "match": ["Column: region"],
                       "content": {"changed_something_it_shouldnt": True, "concerns": ["State codes were re-cased."]}})
    fixture = tmp_path / "critic_rejects.json"
    fixture.write_text(json.dumps(entries), encoding="utf-8")
    monkeypatch.setenv("LLM_MOCK", str(fixture))
    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from sherlock.main import create_app
    with TestClient(create_app()) as client:  # built after LLM_MOCK points at this fixture
        ds = offered(client)
        job = client.post(f"{API}/datasets/{ds['id']}/clean", json={}).json()
        assert finished(client, job["id"])["status"] == "done"
        wait_status(client, ds["id"], "ready", "failed")
        report = client.get(f"{API}/datasets/{ds['id']}/report").json()
    assert [s["summary"] for s in report["steps"]] == ["Parse money as numbers (amount)"]
    skipped = {(s["detector"], s["column"]): s["reason"] for s in report["skipped"]}
    assert skipped[("whitespace_case", "region")] == ("Skipped: the review found it changed values it shouldn't have "
                                                      "(State codes were re-cased)")


def test_a_vetoed_parse_falls_to_codes_own_which_is_flagged_when_rejected_too(monkeypatch, tmp_path):
    # PRD CLEAN-4e: the critic rejects the model's parse of amounts that each read one way; code's own parse
    # takes its place, and when the critic rejects that too the step is flagged, not skipped.
    entries = json.loads(FIXTURES.read_text(encoding="utf-8"))
    entries.insert(0, {"purpose": "critic", "match": ["Column: amount"],
                       "content": {"changed_something_it_shouldnt": True, "concerns": ["The column's type changed."]}})
    fixture = tmp_path / "critic_rejects_parse.json"
    fixture.write_text(json.dumps(entries), encoding="utf-8")
    monkeypatch.setenv("LLM_MOCK", str(fixture))
    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from sherlock.main import create_app
    with TestClient(create_app()) as client:
        ds = offered(client)
        job = client.post(f"{API}/datasets/{ds['id']}/clean", json={}).json()
        assert finished(client, job["id"])["status"] == "done"
        wait_status(client, ds["id"], "ready", "failed")
        report = client.get(f"{API}/datasets/{ds['id']}/report").json()
    amount = next(s for s in report["steps"] if s["summary"] == "Parse numbers (amount)")
    assert amount["gate"] == "flag"
    assert amount["flag_reason"].startswith("the review objected, but code's own parse reads every value one way")


def test_a_users_step_runs_first_and_records_what_they_asked(client):
    # PRD CLEAN-8b: a step added to the plan in plain words runs before Sherlock's fixes, and its step
    # records the instruction.
    ds = offered(client)
    plan = client.post(f"{API}/datasets/{ds['id']}/clean/plan").json()
    asked = "Make every region title case without stray spaces"
    r = client.patch(f"{API}/clean-plans/{plan['id']}", json={"ops": [{"op": "add", "column": "region", "instruction": asked}]})
    assert r.status_code == 200, r.text
    assert r.json()["summary"] == "Added 1 step on region."
    mine = r.json()["items"][0]
    assert (mine["module"], mine["source"], mine["column"], mine["ticked"]) == ("yours", "you", "region", True)
    bad = client.patch(f"{API}/clean-plans/{plan['id']}", json={"ops": [{"op": "add", "column": "ghost", "instruction": "x"}]})
    assert bad.status_code == 422 and "isn't a column" in bad.json()["error"]["message"]

    job = client.post(f"{API}/datasets/{ds['id']}/clean", json={"plan_id": plan["id"]}).json()
    assert finished(client, job["id"])["status"] == "done"
    wait_status(client, ds["id"], "ready", "failed")
    logs = [d for t, d in events_of(ds["id"]) if t == "job.log" and d["job_id"] == job["id"] and d.get("icon") == "running"]
    assert logs[0]["text"] == f"Your step: {asked}"  # before every issue
    report = client.get(f"{API}/datasets/{ds['id']}/report").json()
    assert report["steps"][0]["summary"] == "Title case without stray spaces (region)"
    decision = report["decisions"][0]
    assert decision["asked"] == asked and decision["question"] == "How to do what you asked in region?"
    [yours] = report["your_steps"]
    assert yours["item_id"] == mine["id"] and yours["outcome"] in ("fixed", "flagged") and yours["step_no"] == report["steps"][0]["no"]
    regions = {v["value"] for v in next(c for c in client.get(f"{API}/datasets/{ds['id']}/datacard").json()["columns"]
                                       if c["name"] == "region")["top_values"]}
    assert regions == {"North", "South", "East"}


CITIES = ("id,city,score\n" + "\n".join(f"{i},{'' if i % 5 == 0 else ['Paris', 'Lyon', 'Nice'][i % 3]},{i % 7}"
                                        for i in range(1, 41)) + "\n").encode()


def test_a_rewritten_fix_asking_for_a_placeholder_is_still_skipped(client):
    # The hard checks bind the user's instructions too: "fill with Unknown" fails placeholder_fill.
    ds = offered(client, CITIES)
    plan = client.post(f"{API}/datasets/{ds['id']}/clean/plan").json()
    city = item(plan, "missing|city")
    r = client.patch(f"{API}/clean-plans/{plan['id']}", json={"ops": [
        {"op": "set_instruction", "item_id": city["id"], "instruction": "Fill the missing cities with the word Unknown"}]})
    assert r.json()["summary"] == "Rewrote missing values in city."
    job = client.post(f"{API}/datasets/{ds['id']}/clean", json={"plan_id": plan["id"]}).json()
    assert finished(client, job["id"])["status"] == "done"
    report = client.get(f"{API}/datasets/{ds['id']}/report").json()
    assert report["steps"] == []
    [yours] = report["your_steps"]
    assert yours["outcome"] == "skipped" and yours["instruction"] == "Fill the missing cities with the word Unknown"
    assert "placeholder_fill" in yours["reason"] and "'Unknown'" in yours["reason"]
    # The diagnosis said "leave as is", but the user asked: candidates were still tried.
    assert not yours["reason"].startswith("Left as is")


@pytest.fixture
def one_step(monkeypatch):
    monkeypatch.setenv("CLEAN_MAX_STEPS", "1")
    get_settings.cache_clear()


def test_issues_a_budget_left_unreached_are_listed_as_not_attempted(one_step, client):
    # PRD CLEAN-6: a run that ends on its budget lists what it didn't reach (skip_kind "budget").
    ds = offered(client)
    job = client.post(f"{API}/datasets/{ds['id']}/clean", json={}).json()
    assert finished(client, job["id"])["status"] == "done"
    report = client.get(f"{API}/datasets/{ds['id']}/report").json()
    assert report["ended_by"] == "steps" and report["attempted"] == 1
    unreached = [s for s in report["skipped"] if s["skip_kind"] == "budget"]
    assert unreached and all(s["reason"] == "Not reached: the run hit its issue budget" for s in unreached)
    assert report["counts"]["not_attempted"] >= len(unreached)


def test_a_plan_at_a_shallow_depth_lists_and_cleans_only_its_layers(client):
    # PRD CLEAN-15: the offer's slider picks the depth; the setting is the default; nothing deeper is attempted.
    assert client.put(f"{API}/me/settings", json={"clean_depth": 1}).status_code == 200
    ds = offered(client)
    plan = client.post(f"{API}/datasets/{ds['id']}/clean/plan").json()
    assert plan["depth"] == 1
    keys = {i["key"] for i in plan["items"]}
    assert {"numbers_as_text|amount", "whitespace_case|region"} <= keys and "id_candidates|customer_id" not in keys
    region = item(plan, "whitespace_case|region")
    client.patch(f"{API}/clean-plans/{plan['id']}", json={"ops": [{"op": "untick", "item_id": region["id"]}]})
    deeper = client.post(f"{API}/datasets/{ds['id']}/clean/plan", json={"depth": 2})
    assert deeper.status_code == 200 and deeper.json()["id"] == plan["id"] and deeper.json()["depth"] == 2
    assert "id_candidates|customer_id" in {i["key"] for i in deeper.json()["items"]}
    assert not item(deeper.json(), "whitespace_case|region")["ticked"]  # the untick survives the new depth
    assert client.post(f"{API}/datasets/{ds['id']}/clean/plan", json={"depth": 1}).json()["depth"] == 1
    assert client.post(f"{API}/datasets/{ds['id']}/clean/plan", json={"depth": 6}).status_code == 422

    job = client.post(f"{API}/datasets/{ds['id']}/clean", json={"plan_id": plan["id"]}).json()
    assert finished(client, job["id"])["status"] == "done"
    report = client.get(f"{API}/datasets/{ds['id']}/report").json()
    skipped = {(s["detector"], s["column"]): s["reason"] for s in report["skipped"]}
    assert skipped[("id_candidates", "customer_id")] == "Deeper than the cleaning depth you chose"
