"""The cleaning plan (PRD CLEAN-8a, CLEAN-8b; TRD §7.2): what Clean with AI will try, shown before it runs.

The plan is built from the current version's DataCard: the code detectors' issues, each with its
count and planned action (`Finding.proposal`), so no number comes from the model (Rule 2). One item
per issue key (`detector|column`); when two findings share a key (exact and near duplicates are both
`duplicates|None`), the item is the most severe one, the one the Cleaner attempts. Every fix that can
change data starts ticked. Leakage and ID-like columns are info rows under "Marked, not changed".

The user can untick fixes, one at a time or a whole module; `apply_ops` is the one place a plan
changes. (`source` and `instruction` are for the user's own steps and rewritten fixes, CLEAN-8b; until
then every item is Sherlock's, with no instruction.)
A plan made on an older version is merged onto the current one (`merge`) before it's shown or started.
Plans are stored in `clean_plans` (Schema §2.21), at most one draft per dataset.
"""

import json
import sqlite3

from sherlock.db.util import new_id, now_iso

# Display order; "Your steps" comes first.
MODULES = {
    "yours": "Your steps",
    "types": "Types and parsing",
    "missing": "Missing and placeholder values",
    "text": "Spelling and formatting",
    "records": "Duplicates and broken records",
    "outliers": "Outliers",
    "other": "Other checks",
    "kept": "Marked, not changed",
}
DETECTOR_MODULE = {
    "mixed_types": "types", "numbers_as_text": "types", "ambiguous_dates": "types", "unit_mixes": "types",
    "missing": "missing", "sentinels": "missing",
    "whitespace_case": "text", "near_duplicate_categories": "text", "mojibake": "text",
    "duplicates": "records", "cross_column": "records", "functional_dependency": "records", "impossible_values": "records",
    "outliers": "outliers",
    "leakage": "kept", "id_candidates": "kept",
}
# Plain words for an issue, as the offer and the plan panel show them (the web's LABELS).
LABELS = {
    "missing": "missing values", "mixed_types": "mixed types", "sentinels": "placeholder values",
    "whitespace_case": "spacing or case variants", "near_duplicate_categories": "near-duplicate categories",
    "duplicates": "duplicate rows", "impossible_values": "impossible values", "numbers_as_text": "numbers stored as text",
    "ambiguous_dates": "ambiguous dates", "mojibake": "garbled characters", "unit_mixes": "mixed units",
    "cross_column": "values out of order", "functional_dependency": "broken dependencies", "outliers": "outliers",
    "id_candidates": "looks like an ID", "leakage": "records the outcome",
}
NEVER_CHANGE = {"leakage": "Records the outcome, so it is marked as leakage and not changed",
                "id_candidates": "Looks like an ID column, so it is left as is"}
SKIP_TEXT = {"leakage": "excluded from models", "id_candidates": "left as is"}
MAX_EXAMPLES = 5
OPS = ("tick", "untick", "tick_module", "untick_module")


class PlanError(ValueError):
    """An op that can't apply: an unknown item or module, or an item that can't be ticked."""


def key(issue: dict) -> str:
    return f"{issue['detector']}|{issue['column']}"


def never_change(issue: dict, card: dict) -> tuple[str, str] | None:
    """Columns that record the outcome or identify rows are marked, never changed, whatever the issue:
    (reason, kind), kind being a `SKIP_TEXT` key, or None for an issue the Cleaner may fix."""
    reason = NEVER_CHANGE.get(issue["detector"])
    if reason is not None:
        return reason, issue["detector"]
    leaking = {c["column"] for c in card.get("leakage_candidates", [])}
    if issue["column"] in leaking:
        return f"{issue['column']} records the outcome, so it is not changed", "leakage"
    if issue["column"] in set(card.get("id_columns", [])):
        return f"{issue['column']} looks like an ID column, so it is left as is", "id_candidates"
    return None


def fix_name(item: dict) -> str:
    """"outliers in fare", "duplicate rows"."""
    what = LABELS.get(item["detector"], item["detector"].replace("_", " "))
    return f"{what} in {item['column']}" if item["column"] else what


def _item(issue: dict, card: dict, item_id: str | None = None) -> dict:
    kept = never_change(issue, card)
    module = "kept" if kept else DETECTOR_MODULE.get(issue["detector"], "other")
    item = {
        "id": item_id or new_id("pit"), "source": "sherlock", "key": key(issue), "detector": issue["detector"],
        "column": issue["column"], "count": issue["count"], "severity": issue["severity"],
        "action": issue.get("proposal") or "", "instruction": None, "examples": list(issue.get("examples") or [])[:MAX_EXAMPLES],
        "ticked": kept is None, "change": kept is None, "module": module,
    }
    if kept:
        item["reason"] = kept[0]
    return item


def diagnose(card: dict) -> list[dict]:
    """The plan's items for a DataCard, most severe first, every changeable fix ticked."""
    items: dict[str, dict] = {}
    for issue in sorted(card["issues"], key=lambda i: -i["severity"]):
        if key(issue) not in items:  # a shared key: the most severe finding is the one attempted
            items[key(issue)] = _item(issue, card)
    return list(items.values())


def merge(old: list[dict], card: dict) -> tuple[list[dict], list[str]]:
    """A plan carried onto a newer version: ticks kept by key, keys that went away dropped, new keys
    ticked. Returns the items and what changed, in code-written sentences."""
    by_key = {i["key"]: i for i in old if i["key"]}
    items, notes = [], []
    fresh = diagnose(card)
    added = 0
    for item in fresh:
        before = by_key.get(item["key"])
        if before is None:
            added += 1
            items.append(item)
            continue
        item["id"] = before["id"]
        if item["change"] and before["change"]:
            item["ticked"] = before["ticked"]
        items.append(item)
    gone = [i for k, i in by_key.items() if k not in {f["key"] for f in fresh}]
    if gone:
        notes.append(f"{_count(len(gone), 'fix', 'fixes')} no longer needed: {', '.join(fix_name(i) for i in gone[:5])}"
                     + ("…" if len(gone) > 5 else "") + ".")
    if added:
        notes.append(f"{_count(added, 'new fix', 'new fixes')} found, ticked.")
    return _ordered(items), notes


def _ordered(items: list[dict]) -> list[dict]:
    order = list(MODULES)
    return sorted(items, key=lambda i: order.index(i["module"]) if i["module"] in order else len(order))


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def apply_ops(items: list[dict], ops: list[dict]) -> tuple[list[dict], str]:
    """Apply ops to a copy of the items, all or nothing (a bad op raises PlanError). Returns the items
    and a code-written summary of what changed."""
    items = [dict(i) for i in items]
    by_id = {i["id"]: i for i in items}
    done: dict[str, list[str]] = {"ticked": [], "unticked": []}

    def tick(i: dict, on: bool) -> None:
        if not i["change"]:
            raise PlanError(f"{i['column']} is marked, not changed, so it can't be ticked.")
        if i["ticked"] != on:
            i["ticked"] = on
            done["ticked" if on else "unticked"].append(fix_name(i))

    for op in ops:
        kind = op.get("op")
        if kind in ("tick", "untick"):
            found = by_id.get(op.get("item_id"))
            if found is None:
                raise PlanError(f"There's no item {op.get('item_id')!r} in this plan.")
            tick(found, kind == "tick")
        elif kind in ("tick_module", "untick_module"):
            module = op.get("module")
            if module not in MODULES or module == "kept":
                raise PlanError(f"There's no module {module!r} with fixes to tick.")
            for i in items:
                if i["module"] == module and i["change"]:
                    tick(i, kind == "tick_module")
        else:
            raise PlanError(f"Unknown op {kind!r}; use one of {', '.join(OPS)}.")
    return items, summary(done)


def summary(done: dict[str, list[str]]) -> str:
    parts = []
    for word, names in (("Ticked", done["ticked"]), ("Unticked", done["unticked"])):
        if names:
            parts.append(f"{word} {_count(len(names), 'fix', 'fixes')}: {', '.join(names)}.")
    return " ".join(parts) or "The plan already said that, so nothing changed."


def ticked(items: list[dict]) -> list[dict]:
    return [i for i in items if i["change"] and i["ticked"]]


def skip_keys(items: list[dict]) -> set[str]:
    """The issue keys a started plan leaves out: its unticked fixes."""
    return {i["key"] for i in items if i["key"] and i["change"] and not i["ticked"]}


# --- storage (Schema §2.21) -----------------------------------------------------------------------


def to_plan(row: sqlite3.Row, notes: list[str] | None = None) -> dict:
    """The TRD §4.4 `CleanPlan`."""
    out = {"id": row["id"], "dataset_id": row["dataset_id"], "version": row["version"], "status": row["status"],
           "source": row["source"], "job_id": row["job_id"], "items": json.loads(row["items_json"]),
           "created_at": row["created_at"], "updated_at": row["updated_at"]}
    if notes:
        out["notes"] = notes
    return out


def get(db: sqlite3.Connection, plan_id: str) -> sqlite3.Row | None:
    return db.execute("SELECT * FROM clean_plans WHERE id = ?", (plan_id,)).fetchone()


def draft_id(db: sqlite3.Connection, dataset_id: str) -> str | None:
    row = db.execute("SELECT id FROM clean_plans WHERE dataset_id = ? AND status = 'draft'", (dataset_id,)).fetchone()
    return row["id"] if row else None


def create(db: sqlite3.Connection, dataset: sqlite3.Row, card: dict, source: str = "user") -> sqlite3.Row:
    """A new draft diagnosed on the card's version (the caller has checked there is none)."""
    pid, now = new_id("pln"), now_iso()
    db.execute("INSERT INTO clean_plans (id, dataset_id, version, items_json, status, source, job_id, created_at, updated_at) "
               "VALUES (?, ?, ?, ?, 'draft', ?, NULL, ?, ?)",
               (pid, dataset["id"], card["version"], json.dumps(diagnose(card), default=str), source, now, now))
    return get(db, pid)


def save(db: sqlite3.Connection, plan_id: str, items: list[dict], version: int | None = None) -> sqlite3.Row:
    if version is None:
        db.execute("UPDATE clean_plans SET items_json = ?, updated_at = ? WHERE id = ?",
                   (json.dumps(items, default=str), now_iso(), plan_id))
    else:
        db.execute("UPDATE clean_plans SET items_json = ?, version = ?, updated_at = ? WHERE id = ?",
                   (json.dumps(items, default=str), version, now_iso(), plan_id))
    return get(db, plan_id)


def current(db: sqlite3.Connection, row: sqlite3.Row, dataset: sqlite3.Row, card_for) -> tuple[sqlite3.Row, list[str]]:
    """A draft made on an older version, merged onto the current one and saved; `card_for(dataset)`
    returns the current version's DataCard. Returns the row and what the merge changed."""
    if row["status"] != "draft" or row["version"] == dataset["current_version"]:
        return row, []
    card = card_for(dataset)
    items, notes = merge(json.loads(row["items_json"]), card)
    return save(db, row["id"], items, card["version"]), notes or ["The data changed, so the plan was checked again."]


def set_status(db: sqlite3.Connection, plan_id: str, status: str, job_id: str | None = None) -> None:
    db.execute("UPDATE clean_plans SET status = ?, job_id = coalesce(?, job_id), updated_at = ? WHERE id = ?",
               (status, job_id, now_iso(), plan_id))


def discard_drafts(db: sqlite3.Connection, dataset_id: str) -> None:
    db.execute("UPDATE clean_plans SET status = 'discarded', updated_at = ? WHERE dataset_id = ? AND status = 'draft'",
               (now_iso(), dataset_id))
