"""Saving a check and showing its effect at once (PRD CLEAN-13, TRD §4.4 `/rules`).

A saved, changed or switched-off rule rebuilds the current version's DataCard, so the plan, the
Cleaner and the review see it, and merges an open draft plan onto it (`plan.updated`). Its count comes
from running it on the current version, by code, so it shows as soon as the rule is saved.
"""

import json
import sqlite3

from sherlock.cleaning import plan as plans
from sherlock.cleaning.rules import interpreter, store
from sherlock.cleaning.rules.evidence import backed
from sherlock.cleaning.rules.kinds import RuleError
from sherlock.config import Settings
from sherlock.jobs.events import emit
from sherlock.storage import VersionConnections, dataset_dir


def columns(card: dict) -> dict[str, str]:
    """The file's columns and their types, as a rule is checked against them."""
    return {c["name"]: c["type"] for c in card["columns"]}


def frame_for(settings: Settings, cache: VersionConnections, db, dataset: sqlite3.Row, version: int | None = None):
    """The detector frame of a version (the current one by default), as rules run on it."""
    from sherlock.profile.datacard import build_frame, load_frame

    version = version or dataset["current_version"]
    row = db.execute("SELECT parquet_path FROM versions WHERE dataset_id = ? AND version = ?",
                     (dataset["id"], version)).fetchone()
    with cache.connection(dataset["id"], version,
                          dataset_dir(settings, dataset["user_id"], dataset["id"]) / row["parquet_path"]) as conn:
        df, types, _ = load_frame(conn)
    return build_frame(df, types)


def counts(settings: Settings, cache: VersionConnections, dataset: sqlite3.Row, rules: list[dict], db) -> dict[str, dict]:
    """Each rule's count on the current version and the error that stopped it, by rule id."""
    if not rules:
        return {}
    frame = frame_for(settings, cache, db, dataset)
    out = {}
    for r in rules:
        finding, error = interpreter.run(r, frame, settings.rule_max_s)
        out[r["id"]] = {"count": finding.count if finding else 0, "error": error}
    return out


def with_counts(settings, db, cache, dataset, rules: list[dict]) -> list[dict]:
    got = counts(settings, cache, dataset, [r for r in rules if r["status"] != "off"], db)
    return [{**r, **got.get(r["id"], {"count": None, "error": None}), "words": interpreter.words(r),
             "evidence": r.get("evidence") or None} for r in rules]


def refresh(settings: Settings, db: sqlite3.Connection, cache: VersionConnections, bus, dataset: sqlite3.Row) -> None:
    """Rebuild the current version's DataCard with the dataset's active rules, and merge an open draft."""
    from sherlock.cleaning import review
    from sherlock.profile import service as profile_service

    version = dataset["current_version"]
    db.execute("DELETE FROM datacards WHERE dataset_id = ? AND version = ?", (dataset["id"], version))
    card = profile_service.get_or_build(settings, db, cache, dataset)
    pid = plans.draft_id(db, dataset["id"])
    row = plans.get(db, pid) if pid else None
    if row is not None and row["version"] == version:
        items, _ = plans.merge(json.loads(row["items_json"]), card,
                               review.stored(db, dataset["id"], version) or {})
        plans.save(db, row["id"], items)
        emit(db, bus, dataset["id"], dataset["user_id"], "plan.updated", {"plan_id": row["id"]})


def add(settings, db, cache, bus, dataset: sqlite3.Row, spec: dict, source: str = "user", status: str = "active",
        every_dataset: bool = False) -> dict:
    """Validate and save a rule on the dataset (RuleError names a bad field), then refresh. With
    `every_dataset` it is the owner's check for every dataset: checked against this one's columns, it
    runs here at once and on any other dataset from its next profile."""
    from sherlock.profile import service as profile_service

    card = profile_service.get_or_build(settings, db, cache, dataset)
    clean = interpreter.validate(spec, columns(card))
    clean |= interpreter.source_of(spec)  # the reason and the web evidence stay with the check
    rule = store.create(db, dataset["user_id"], None if every_dataset else dataset["id"], clean, source, status)
    if status == "active":
        refresh(settings, db, cache, bus, dataset)
    return rule


def apply(settings, db, cache, bus, dataset: sqlite3.Row, row: sqlite3.Row, ops: list[dict], columns_: list[str],
          source: str = "you") -> tuple[sqlite3.Row, str]:
    """Plan ops with `add_rule` among them (TRD §4.4): all are checked first (a bad rule raises RuleError,
    a bad op PlanError, and nothing is saved); then each rule is saved, which adds its item to the plan,
    and the other ops apply. Returns the plan row and the code-written summary."""
    from sherlock.profile import service as profile_service

    rule_ops = [o for o in ops if o.get("op") == "add_rule"]
    picks = [o for o in ops if o.get("op") in SUGGESTION_OPS]
    other = [o for o in ops if o.get("op") != "add_rule" and o.get("op") not in SUGGESTION_OPS]
    card = profile_service.get_or_build(settings, db, cache, dataset)
    specs = [interpreter.validate(o.get("rule") or {}, columns(card)) for o in rule_ops]
    everywhere = [(o.get("rule") or {}).get("scope") == "all" for o in rule_ops]
    suggested = [_suggestion(db, dataset, o.get("rule_id")) for o in picks]
    plans.apply_ops(json.loads(row["items_json"]), other, columns_, source)  # a dry run: all or nothing
    for spec, all_datasets in zip(specs, everywhere):
        add(settings, db, cache, bus, dataset, spec, every_dataset=all_datasets)
    said = [f"Added your check: {interpreter.words(s)}." for s in specs]
    for op, rule in zip(picks, suggested):
        keep = op["op"] == "keep_suggestion"
        if keep:
            change(settings, db, cache, bus, dataset, rule, status="active")
        else:
            store.update(db, rule["id"], status="off")
        said.append(f"{'Kept' if keep else 'Dismissed'} the suggested check: {interpreter.words(rule)}.")
    row = plans.get(db, row["id"])
    items, summary = plans.apply_ops(json.loads(row["items_json"]), other, columns_, source)
    row = plans.save(db, row["id"], items)
    return row, " ".join(said + ([summary] if other or not said else []))


SUGGESTION_OPS = ("keep_suggestion", "dismiss_suggestion")


def _suggestion(db, dataset: sqlite3.Row, rule_id) -> dict:
    rule = store.get(db, rule_id or "")
    if rule is None or rule["dataset_id"] != dataset["id"] or rule["status"] != "suggested":
        raise RuleError("rule_id", "There's no suggested check with that id in this plan.")
    return rule


def suggestions(settings, db, cache, dataset: sqlite3.Row, version: int) -> list[dict]:
    """A plan's suggested checks (PRD CLEAN-14): each with its words, the model's reason, its count by
    code on the current version, its level (the review's, or its kind's default), and its `evidence`
    ({url, title, excerpt, retrieved_at} or null): the page its threshold was found in, checked by code
    (docs/plans/tavily.md §3.3). Sourced suggestions come first."""
    from sherlock.cleaning import review
    from sherlock.cleaning.rules.kinds import KINDS

    rules = [r for r in store.all_for(db, dataset["id"]) if r["status"] == "suggested"]
    if not rules:
        return []
    rated = review.stored(db, dataset["id"], version) or {}
    out = []
    for r in with_counts(settings, db, cache, dataset, rules):
        level = rated.get(f"rule:{r['id']}|{r['column']}") or {}
        out.append({**r, "sev": level.get("sev") or KINDS[r["kind"]].default_level, "sev_reason": level.get("sev_reason")})
    return sorted(out, key=lambda r: r["evidence"] is None)  # stable: the order they were saved otherwise


def change(settings, db, cache, bus, dataset: sqlite3.Row, rule: dict, params: dict | None = None,
           action: str | None = None, status: str | None = None) -> dict:
    """Change a rule's parameters, action or status (active, off; a suggestion: kept or dismissed)."""
    from sherlock.profile import service as profile_service

    if status is not None and status not in ("active", "off"):
        raise RuleError("status", "The status is active or off.")
    if rule.get("scope") == "all" and (params is not None or action is not None):
        raise RuleError("scope", "A check for every dataset can be switched on or off; to change it, add it again.")
    spec = None
    if params is not None or action is not None:
        card = profile_service.get_or_build(settings, db, cache, dataset)
        draft = {k: rule[k] for k in ("kind", "column", "params", "action")}
        draft.update({k: v for k, v in (("params", params), ("action", action)) if v is not None})
        spec = interpreter.validate(draft, columns(card))
        carried = interpreter.source_of(rule)
        # A source says what the page states: an edit that leaves the check no longer in the excerpt drops it.
        if "evidence" in carried and not backed(spec, carried["evidence"]["excerpt"]):
            del carried["evidence"]
        spec |= carried
    updated = store.update(db, rule["id"], spec, status)
    refresh(settings, db, cache, bus, dataset)
    return updated
