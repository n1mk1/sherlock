"""Chat actions that change things (TRD §8.2, PRD ASK-10), Implementation Plan D8.5.

Data changes asked for in chat never apply on their own: `edit_cells` and `clean_selection` store a
proposal (Schema §2.15) that the chat shows with Approve and Reject. `edit_plan` (PRD CLEAN-8b)
changes the open cleaning plan at once, since nothing touches the data until Start. Approving re-checks that the
data is still the version the proposal was computed on (else the proposal expires), then commits an
edit step or opens the cleaning plan for the proposal's rows, the same code the CSV tab uses. "Export a notebook" needs
no model call: the options come from the wording and the answer opens the export dialog.
"""

import json
import re
import sqlite3

from sherlock.agent import prompts
from sherlock.agent.answerers import CantAnswer, Toolkit
from sherlock.cleaning import plan as plans
from sherlock.db.util import new_id, now_iso
from sherlock.errors import ApiError
from sherlock.jobs.events import emit
from sherlock.llm.client import StructuredOutputError, data_block
from sherlock.llm.schemas import EditsDraft, PlanEdits
from sherlock.profile import service as profile_service
from sherlock.rows.query import ident
from sherlock.widgets import service as ws

EXPORT = re.compile(r"\b(export|download|save|give me)\b.*\b(notebook|ipynb|jupyter)\b|\b(notebook|ipynb|jupyter)\b.*\b(export|download)\b", re.I)
SYSTEM_COLUMNS = ("_row_id", "_quarantine_reason")
MAX_PROMPT_CELLS = 60
PREVIEW = 20


# --- notebook export from chat (App Flow §17.1) -----------------------------------------------------

def export_options(text: str) -> dict:
    """The dialog's options, pre-filled from the wording ("export a notebook without the data")."""
    t = text.lower()
    out = {}
    if re.search(r"\b(without|no|minus|skip)\s+(the\s+)?(raw\s+)?(data|csv|file)\b", t):
        out["include_data"] = False
    if re.search(r"\b(without|no|skip)\s+(the\s+)?(story\s+)?(cards|stories)\b", t):
        out["include_cards"] = False
    if re.search(r"\b(with|include|including|plus|and)\s+(the\s+|my\s+)?(canvas\s+|flow\s+)?notes\b", t):
        out["include_notes"] = True
    if re.search(r"\b(without|no|skip)\s+(the\s+)?(ml|models?|runs?|analys[ie]s)\b", t):
        out["include_runs"] = False
    return out


# --- proposals ---------------------------------------------------------------------------------------

def to_proposal(row: sqlite3.Row) -> dict:
    """The TRD §6.8 `Proposal`: `{ id, kind, base_version, summary, edits?, scope?, impact, status }`."""
    payload = json.loads(row["payload_json"])
    return {"id": row["id"], "kind": row["kind"], "base_version": row["base_version"], "status": row["status"],
            "result_step_id": row["result_step_id"], **payload}


def _store(db: sqlite3.Connection, dataset: sqlite3.Row, message_id: str, kind: str, payload: dict) -> dict:
    pid = new_id("prp")
    db.execute("INSERT INTO proposals (id, dataset_id, message_id, kind, base_version, payload_json, status, created_at) "
               "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
               (pid, dataset["id"], message_id, kind, dataset["current_version"], json.dumps(payload, default=str), now_iso()))
    return to_proposal(db.execute("SELECT * FROM proposals WHERE id = ?", (pid,)).fetchone())


def _selected(context: dict) -> tuple[list[int], list[str]]:
    cells = context.get("selected_cells") or {}
    rows = [int(r) for r in cells.get("row_ids") or [] if isinstance(r, int | float)][:500]
    cols = [c for c in cells.get("columns") or [] if isinstance(c, str)][:50]
    return rows, cols


def propose_edits(kit: Toolkit, question: str, context: dict, types: dict[str, str]) -> dict:
    """`edit_cells`: `medium` (schema `EditsDraft`) turns the request into edits, checked against the
    current version; the proposal shows each cell's value now and after."""
    rows, cols = _selected(context)
    cols = [c for c in cols if c in types] or list(types)[:6]
    cells_text = ""
    with ws.connection(kit.env, kit.dataset, kit.dataset["current_version"]) as conn:
        if rows:
            shown = rows[:max(1, MAX_PROMPT_CELLS // max(1, len(cols)))]
            got = conn.execute(f"SELECT _row_id, {', '.join(ident(c) for c in cols)} FROM t WHERE _row_id IN "  # noqa: S608
                               f"({', '.join(str(r) for r in shown)}) ORDER BY _row_id").fetchall()
            lines = [f"_row_id {r[0]}: " + " | ".join(f"{c} = {v!r}" for c, v in zip(cols, r[1:], strict=True)) for r in got]
            cells_text = (f"The selected cells ({len(rows)} rows × {', '.join(cols)}):\n" + data_block("\n".join(lines)) + "\n")

        def check(d: EditsDraft) -> None:
            for e in d.edits:
                if e.column in SYSTEM_COLUMNS or e.column not in types:
                    raise ValueError(f"{e.column!r} is not a column you can edit; use one of {', '.join(list(types)[:30])}")

        messages = [{"role": "system", "content": prompts.SYSTEM},
                    {"role": "user", "content": prompts.EDITS.format(context=kit.context, cells=cells_text, message=data_block(question))}]
        draft = kit.llm.structured("medium", messages, EditsDraft, purpose="edits", scope=kit.scope, validate=check).value
        edits = list({(e.row_id, e.column): e for e in draft.edits}.values())  # the last edit of a cell wins
        ids = sorted({e.row_id for e in edits})
        used = sorted({e.column for e in edits})
        found = {r[0]: dict(zip(used, r[1:], strict=True)) for r in conn.execute(
            f"SELECT _row_id, {', '.join(ident(c) for c in used)} FROM t WHERE _row_id IN ({', '.join(map(str, ids))})").fetchall()}  # noqa: S608
    missing = [i for i in ids if i not in found]
    if missing:
        raise CantAnswer(f"Row {missing[0]} isn't in this version of the file, so I can't change it.")
    out = [{"row_id": e.row_id, "column": e.column, "value": e.value, "before": found[e.row_id][e.column]} for e in edits]
    changed = [e for e in out if not _same(e["before"], e["value"])]
    if not changed:
        raise CantAnswer("Those cells already hold those values, so there's nothing to change.")
    rows_hit = len({e["row_id"] for e in changed})
    cols_hit = sorted({e["column"] for e in changed})
    # Written by code: the model's own words could carry numbers the user never typed.
    summary = (f"Change {len(changed):,} {'cell' if len(changed) == 1 else 'cells'} in {rows_hit:,} "
               f"{'row' if rows_hit == 1 else 'rows'}: {', '.join(cols_hit)}")
    payload = {"summary": summary, "edits": changed,
               "impact": {"cells_changed": len(changed), "rows_affected": len({e["row_id"] for e in changed})}}
    return _store(kit.env.db, kit.dataset, kit.scope.message_id, "edit_cells", payload)


def _same(before, value: str | None) -> bool:
    """Whether a cell already holds the requested value (numbers compared as numbers: 100.0 is "100")."""
    if before is None or value in (None, ""):
        return before is None and value in (None, "")
    if isinstance(before, int | float) and not isinstance(before, bool):
        try:
            return float(value) == float(before)
        except ValueError:
            return False
    return str(before) == value


def propose_clean(db: sqlite3.Connection, dataset: sqlite3.Row, context: dict, message_id: str) -> dict:
    """`clean_selection`: Clean with AI on the selection (the context's, or the selected cells' rows),
    else on the whole file. No model call until it's approved."""
    rows, _ = _selected(context)
    selection_id = context.get("selection_id")
    if not selection_id and rows:
        selection_id = new_id("sel")
        db.execute("INSERT INTO selections (id, dataset_id, version, predicate, row_ids_json, row_count, label, created_at) "
                   "VALUES (?, ?, ?, NULL, ?, ?, 'Selected in CSV', ?)",
                   (selection_id, dataset["id"], dataset["current_version"], json.dumps(rows), len(rows), now_iso()))
    if selection_id:
        sel = db.execute("SELECT row_count FROM selections WHERE id = ? AND dataset_id = ?", (selection_id, dataset["id"])).fetchone()
        if sel is None:
            raise CantAnswer("That selection is gone; select the rows again.")
        n = sel["row_count"]
        payload = {"summary": f"Clean with AI on the {n:,} selected {'row' if n == 1 else 'rows'}",
                   "scope": {"kind": "selection", "selection_id": selection_id}}
    else:
        n = dataset["row_count"] or 0
        payload = {"summary": "Clean with AI on the whole file", "scope": {"kind": "all", "selection_id": None}}
    payload["impact"] = {"cells_changed": 0, "rows_affected": n}
    return _store(db, dataset, message_id, "clean_selection", payload)


# --- the cleaning plan from chat (PRD CLEAN-8b) -------------------------------------------------------


def edit_plan(kit: Toolkit, question: str, context: dict) -> str:
    """`edit_plan`: `medium` (schema `PlanEdits`) reads the open plan's items, by ref, and the message,
    and returns ops that `plan.apply_ops` checks (a failure gets the client's one repair). The ops
    apply at once and the reply is apply_ops' code-written summary; `plan.updated` tells the panel."""
    db, dataset = kit.env.db, kit.dataset
    row = plans.get(db, context.get("plan_id") or "")
    if row is None or row["dataset_id"] != dataset["id"] or row["status"] != "draft":
        raise CantAnswer("That cleaning plan isn't open any more. Press Clean with AI to open one.")
    row, _ = plans.current(db, row, dataset, lambda d: profile_service.get_or_build(kit.env.settings, db, kit.env.cache, d))
    items = json.loads(row["items_json"])
    columns = [c for c in ws.user_types(kit.env, dataset, dataset["current_version"])]
    refs = {f"f{n}": i for n, i in enumerate(items, 1)}
    lines = [" · ".join([ref, i["module"], i["column"] or "rows", plans.LABELS.get(i["detector"], i["detector"].replace("_", " ")),
                         ("ticked" if i["ticked"] else "unticked") if i["change"] else "kept",
                         f"source {i['source']}", i["instruction"] or i["action"]]) for ref, i in refs.items()]

    def to_ops(d: PlanEdits) -> list[dict]:
        ops = []
        for e in d.ops:
            op: dict = {"op": e.op}
            if e.op in ("tick", "untick", "set_instruction", "remove"):
                if e.item not in refs:
                    raise ValueError(f"{e.item!r} isn't a ref of the plan; use one of f1 to f{len(refs)}")
                op["item_id"] = refs[e.item]["id"]
            if e.op in ("tick_module", "untick_module"):
                op["module"] = e.module
            if e.op in ("set_instruction", "add"):
                op["instruction"] = e.instruction
            if e.op == "add":
                op["column"] = e.column
            ops.append(op)
        plans.apply_ops(items, ops, columns, source="chat")  # raises PlanError, a ValueError: the repair sees it
        return ops

    messages = [{"role": "system", "content": prompts.SYSTEM},
                {"role": "user", "content": prompts.PLAN_EDITS.format(columns=data_block(", ".join(columns)),
                                                                      plan=data_block("\n".join(lines)), message=data_block(question))}]
    def check(d: PlanEdits) -> None:
        to_ops(d)

    try:
        draft = kit.llm.structured("medium", messages, PlanEdits, purpose="plan_edits", scope=kit.scope, validate=check).value
    except StructuredOutputError as exc:
        raise CantAnswer(f"I couldn't change the plan: {str(exc).split(': ', 1)[-1][:200]}") from None
    new_items, summary = plans.apply_ops(items, to_ops(draft), columns, source="chat")
    plans.save(db, row["id"], new_items)
    emit(db, kit.env.bus, dataset["id"], dataset["user_id"], "plan.updated", {"plan_id": row["id"]})
    return summary


def approve(app, db: sqlite3.Connection, dataset: sqlite3.Row, row: sqlite3.Row) -> dict:
    """`POST /proposals/{id}/approve`: `{ step, version }` for edits; for a clean, the `CleanPlan` it
    opens with the proposal's scope (PRD CLEAN-1: nothing is cleaned without Start cleaning)."""
    from sherlock.rows.edits import CellEdit, EditBatch, save
    from sherlock.routers.cleaning import CleanScope, open_plan
    from sherlock.steps.commit import Context

    if row["status"] != "pending":
        raise ApiError(409, "conflict", f"This proposal was already {row['status']}.")
    if row["base_version"] != dataset["current_version"]:
        db.execute("UPDATE proposals SET status = 'expired', resolved_at = ? WHERE id = ?", (now_iso(), row["id"]))
        raise ApiError(409, "conflict", f"The data changed since this was proposed (now version {dataset['current_version']}). "
                       "Ask again to get a new proposal.", extra={"current_version": dataset["current_version"]})
    payload = json.loads(row["payload_json"])
    if row["kind"] == "edit_cells":
        batch = EditBatch(base_version=row["base_version"],
                          edits=[CellEdit(row_id=e["row_id"], column=e["column"], value=e["value"]) for e in payload["edits"]])
        result = save(Context(app.state.settings, db, app.state.duckdb, app.state.bus), dataset, batch)
        db.execute("UPDATE proposals SET status = 'approved', result_step_id = ?, resolved_at = ? WHERE id = ?",
                   (result["step"]["id"], now_iso(), row["id"]))
        return {"step": result["step"], "version": result["version"]}
    if row["kind"] == "clean_selection":
        plan, _ = open_plan(app, db, dataset, CleanScope(**{**payload["scope"], "row_ids": None}))
        db.execute("UPDATE proposals SET status = 'approved', resolved_at = ? WHERE id = ?", (now_iso(), row["id"]))
        return plan
    raise ApiError(422, "invalid", f"Proposals of kind {row['kind']} aren't built.")


def reject(db: sqlite3.Connection, row: sqlite3.Row) -> None:
    if row["status"] == "pending":
        db.execute("UPDATE proposals SET status = 'rejected', resolved_at = ? WHERE id = ?", (now_iso(), row["id"]))
