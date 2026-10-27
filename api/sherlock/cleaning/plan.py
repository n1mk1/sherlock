"""The cleaning plan (PRD CLEAN-8a, CLEAN-8b; TRD §7.2): what Clean with AI will try, shown before it runs.

The plan is built from the current version's DataCard: the code detectors' issues, each with its
count and planned action (`Finding.proposal`), so no number comes from the model (Rule 2). One item
per issue key (`detector|column`); when two findings share a key (exact and near duplicates are both
`duplicates|None`), the item is the most severe one, the one the Cleaner attempts. Every fix that can
change data starts ticked. Leakage and ID-like columns are info rows under "Marked, not changed".

The user can untick fixes, rewrite a fix in plain words (`instruction`), and add steps of their own
(`detector: user_request`), from the panel or from chat; `apply_ops` is the one place a plan changes.
An item's module, label and extra fields come from its detector's spec (`registry`, PRD CLEAN-12): an
ambiguous-dates item carries up to three of its values read both ways (`both_ways`) and the order
the user picks (`date_order`: "dmy", "mdy" or null); a column every date of which reads
both ways is cleaned only with an order (`needs_order`).
A plan made on an older version is merged onto the current one (`merge`) before it's shown or started.
Plans are stored in `clean_plans` (Schema §2.21), at most one draft per dataset.
"""

import json
import sqlite3

from sherlock.cleaning import registry
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
USER_DETECTOR = "user_request"
MAX_INSTRUCTION = 500
MAX_EXAMPLES = 5
OPS = ("tick", "untick", "tick_module", "untick_module", "set_instruction", "set_date_order", "add", "remove")
DATE_ORDERS = {"dmy": "day-first (dd/mm/yyyy)", "mdy": "month-first (mm/dd/yyyy)"}


class PlanError(ValueError):
    """An op that can't apply: an unknown item or module, a column the file doesn't have, …"""


def key(issue: dict) -> str:
    return f"{issue['detector']}|{issue['column']}"


def never_change(issue: dict, card: dict) -> tuple[str, str] | None:
    """Columns that record the outcome or identify rows are marked, never changed, whatever the issue
    but a type fix on an ID column (`spec.type_fix`: it only makes values readable, so a column taken
    for an ID by mistake still gets its types fixed): (reason, kind), kind being the id of the
    detector whose `skip_text` the log shows, or None for an issue the Cleaner may fix."""
    spec = registry.get(issue["detector"])
    if spec.never_change is not None:
        return spec.never_change, spec.id
    leaking = {c["column"] for c in card.get("leakage_candidates", [])}
    if issue["column"] in leaking:
        return f"{issue['column']} records the outcome, so it is not changed", "leakage"
    if issue["column"] in set(card.get("id_columns", [])) and not spec.type_fix:
        return f"{issue['column']} looks like an ID column, so it is left as is", "id_candidates"
    return None


def needs_order(issue: dict) -> bool:
    """An issue whose plan item says it is cleaned only once the user picks an order (a date column
    every value of which reads both ways): no reading of the data settles it, so the Cleaner doesn't
    guess one."""
    extras = registry.get(issue["detector"]).plan_extras
    return bool(extras and extras(issue).get("needs_order"))


def both_ways(values: list) -> list[tuple[str, str, str]]:
    """Up to three values with their day-first and month-first readings: ("03/04/2021", "3 Apr 2021",
    "4 Mar 2021")."""
    import pandas as pd

    from sherlock.cleaning.helpers import parse_dates_smart
    from sherlock.cleaning.verifiers import show

    out = []
    for v in values:
        s = pd.Series([v], dtype=object)
        dmy, mdy = parse_dates_smart(s, order_hint="dmy")[0], parse_dates_smart(s, order_hint="mdy")[0]
        if pd.notna(dmy) and pd.notna(mdy) and dmy != mdy:
            out.append((str(v), show(dmy), show(mdy)))
        if len(out) == 3:
            break
    return out


def fix_name(item: dict) -> str:
    """"outliers in fare", "duplicate rows", "your step on name"."""
    if item["detector"] == USER_DETECTOR:
        return f"your step on {item['column']}" if item["column"] else "your step on the rows"
    what = registry.label(item["detector"])
    return f"{what} in {item['column']}" if item["column"] else what


def _item(issue: dict, card: dict, item_id: str | None = None) -> dict:
    kept = never_change(issue, card)
    spec = registry.get(issue["detector"])
    module = "kept" if kept else spec.group
    item = {
        "id": item_id or new_id("pit"), "source": "sherlock", "key": key(issue), "detector": issue["detector"],
        "column": issue["column"], "count": issue["count"], "severity": issue["severity"],
        "action": issue.get("proposal") or "", "instruction": None, "examples": list(issue.get("examples") or [])[:MAX_EXAMPLES],
        "ticked": kept is None, "change": kept is None, "module": module,
    }
    if kept:
        item["reason"] = kept[0]
    if spec.plan_extras and not kept:
        item.update(spec.plan_extras(issue))
    return item


def diagnose(card: dict) -> list[dict]:
    """The plan's items for a DataCard in module order, most severe first within a module, every
    changeable fix ticked."""
    items: dict[str, dict] = {}
    for issue in sorted(card["issues"], key=lambda i: -i["severity"]):
        if key(issue) not in items:  # a shared key: the most severe finding is the one attempted
            items[key(issue)] = _item(issue, card)
    return _ordered(list(items.values()))


def merge(old: list[dict], card: dict) -> tuple[list[dict], list[str]]:
    """A plan carried onto a newer version: ticks and instructions kept by key, keys that went away
    dropped, new keys ticked; the user's steps kept while their column exists. Returns the items and
    what changed, in code-written sentences."""
    columns = {c["name"] for c in card["columns"]}
    by_key = {i["key"]: i for i in old if i["key"]}
    items, notes = [], []
    for i in old:
        if i["key"] is not None:
            continue
        if i["column"] is None or i["column"] in columns:
            items.append(i)
        else:
            notes.append(f"Dropped your step on {i['column']}: the column is no longer in the file.")
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
            item["instruction"] = before["instruction"]
            if "date_order" in item:
                item["date_order"] = before.get("date_order")
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


def _instruction(text) -> str:
    if not isinstance(text, str) or not text.strip():
        raise PlanError("The instruction can't be empty.")
    text = " ".join(text.split())
    if len(text) > MAX_INSTRUCTION:
        raise PlanError(f"The instruction is {len(text)} characters; keep it under {MAX_INSTRUCTION}.")
    return text


def apply_ops(items: list[dict], ops: list[dict], columns=(), source: str = "you") -> tuple[list[dict], str]:
    """Apply ops to a copy of the items, all or nothing (a bad op raises PlanError). `columns` are the
    file's user columns; `source` marks added steps ("you" from the panel, "chat"). Returns the items
    and a code-written summary of what changed."""
    items = [dict(i) for i in items]
    by_id = {i["id"]: i for i in items}
    done: dict[str, list[str]] = {"ticked": [], "unticked": [], "rewrote": [], "reset": [], "added": [], "removed": [],
                                  "ordered": [], "unordered": []}

    def item(op: dict) -> dict:
        found = by_id.get(op.get("item_id"))
        if found is None:
            raise PlanError(f"There's no item {op.get('item_id')!r} in this plan.")
        return found

    def tick(i: dict, on: bool) -> None:
        if not i["change"]:
            raise PlanError(f"{i['column']} is marked, not changed, so it can't be ticked.")
        if i["ticked"] != on:
            i["ticked"] = on
            done["ticked" if on else "unticked"].append(fix_name(i))

    for op in ops:
        kind = op.get("op")
        if kind in ("tick", "untick"):
            tick(item(op), kind == "tick")
        elif kind in ("tick_module", "untick_module"):
            module = op.get("module")
            if module not in MODULES or module == "kept":
                raise PlanError(f"There's no module {module!r} with fixes to tick.")
            for i in items:
                if i["module"] == module and i["change"]:
                    tick(i, kind == "tick_module")
        elif kind == "set_instruction":
            i = item(op)
            if not i["change"]:
                raise PlanError(f"{i['column']} is marked, not changed, so its fix can't be rewritten.")
            text = op.get("instruction")
            if text is None:
                if i["key"] is None:
                    raise PlanError("A step you added needs an instruction; remove it instead.")
                if i["instruction"] is not None:
                    i["instruction"] = None
                    done["reset"].append(fix_name(i))
                continue
            text = _instruction(text)
            if text != i["instruction"]:
                i["instruction"] = text
                if i["key"] is None:
                    i["action"] = text
                done["rewrote"].append(fix_name(i))
        elif kind == "set_date_order":
            i = item(op)
            if "date_order" not in i:
                raise PlanError(f"{fix_name(i)} has no date order to choose; only ambiguous dates do.")
            order = op.get("order")
            if order is not None and order not in DATE_ORDERS:
                raise PlanError(f"The date order is 'dmy' (day-first) or 'mdy' (month-first), not {order!r}.")
            if order != i["date_order"]:
                i["date_order"] = order
                if order:
                    done["ordered"].append(f"{i['column']} to {DATE_ORDERS[order].split(' ')[0]}")
                else:
                    done["unordered"].append(i["column"])
        elif kind == "add":
            column = op.get("column")
            if column is not None and column not in columns:
                raise PlanError(f"{column!r} isn't a column of this file.")
            text = _instruction(op.get("instruction"))
            new = {"id": new_id("pit"), "source": source, "key": None, "detector": USER_DETECTOR, "column": column,
                   "count": None, "severity": None, "action": text, "instruction": text, "examples": [],
                   "ticked": True, "change": True, "module": "yours"}
            items.append(new)
            by_id[new["id"]] = new
            done["added"].append(column or "the rows")
        elif kind == "remove":
            i = item(op)
            if i["key"] is None:
                items.remove(i)
                del by_id[i["id"]]
                done["removed"].append(i["column"] or "the rows")
            else:
                tick(i, False)  # Sherlock's fixes stay listed; removing one unticks it
        else:
            raise PlanError(f"Unknown op {kind!r}; use one of {', '.join(OPS)}.")
    return _ordered(items), summary(done)


def summary(done: dict[str, list[str]]) -> str:
    parts = []
    for word, names in (("Ticked", done["ticked"]), ("Unticked", done["unticked"])):
        if names:
            parts.append(f"{word} {_count(len(names), 'fix', 'fixes')}: {', '.join(names)}.")
    if done["rewrote"]:
        parts.append(f"Rewrote {', '.join(done['rewrote'])}.")
    if done["reset"]:
        parts.append(f"Put Sherlock's wording back on {', '.join(done['reset'])}.")
    if done["added"]:
        parts.append(f"Added {_count(len(done['added']), 'step', 'steps')} on {', '.join(done['added'])}.")
    if done["removed"]:
        parts.append(f"Removed your {_count(len(done['removed']), 'step', 'steps')} on {', '.join(done['removed'])}.")
    if done["ordered"]:
        parts.append(f"Set the date order of {', '.join(done['ordered'])}.")
    if done["unordered"]:
        parts.append(f"Cleared the date order of {', '.join(done['unordered'])}.")
    return " ".join(parts) or "The plan already said that, so nothing changed."


def ticked(items: list[dict]) -> list[dict]:
    return [i for i in items if i["change"] and i["ticked"]]


def order_instruction(column: str, order: str) -> str:
    """The instruction a chosen date order becomes, as the prompts and the step's decision show it."""
    return f"Read every date in {column} {DATE_ORDERS[order]}: parse it with order_hint \"{order}\"."


def run_params(items: list[dict]) -> dict:
    """What the Cleaner reads from a started plan's frozen items: unticked Sherlock fixes to skip,
    rewritten fixes' instructions by key, the date orders the user picked by key, and the ticked
    user steps in order."""
    return {
        "date_orders": {i["key"]: i["date_order"] for i in items
                        if i["key"] and i["change"] and i["ticked"] and i.get("date_order")},
        "skip_keys": [i["key"] for i in items if i["key"] and i["change"] and not i["ticked"]],
        "instructions": {i["key"]: i["instruction"] for i in items if i["key"] and i["change"] and i["ticked"] and i["instruction"]},
        "user_steps": [{"id": i["id"], "column": i["column"], "instruction": i["instruction"]}
                       for i in items if i["key"] is None and i["ticked"]],
    }


# --- storage (Schema §2.21) -----------------------------------------------------------------------


def to_plan(row: sqlite3.Row, notes: list[str] | None = None) -> dict:
    """The TRD §4.4 `CleanPlan`."""
    out = {"id": row["id"], "dataset_id": row["dataset_id"], "version": row["version"], "status": row["status"],
           "source": row["source"], "job_id": row["job_id"], "items": json.loads(row["items_json"]),
           "scope": json.loads(row["scope_json"]) if row["scope_json"] else None,
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


def set_scope(db: sqlite3.Connection, plan_id: str, scope: dict | None) -> sqlite3.Row:
    """The rows the plan was opened for (`{kind, selection_id, row_ids, rows}`), or None for the whole
    dataset. The panel starts on it, so a reload can't widen a plan opened for some rows."""
    db.execute("UPDATE clean_plans SET scope_json = ?, updated_at = ? WHERE id = ?",
               (json.dumps(scope) if scope else None, now_iso(), plan_id))
    return get(db, plan_id)


def set_status(db: sqlite3.Connection, plan_id: str, status: str, job_id: str | None = None) -> None:
    db.execute("UPDATE clean_plans SET status = ?, job_id = coalesce(?, job_id), updated_at = ? WHERE id = ?",
               (status, job_id, now_iso(), plan_id))


def discard_drafts(db: sqlite3.Connection, dataset_id: str) -> None:
    db.execute("UPDATE clean_plans SET status = 'discarded', updated_at = ? WHERE dataset_id = ? AND status = 'draft'",
               (now_iso(), dataset_id))
