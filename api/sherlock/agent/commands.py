"""Cleaning commands typed in chat (docs/plans/chat-commands.md): "trim the spaces in name", "make fare a number",
"add family_size = sibsp + parch", "delete the rows with no age".

`medium` writes pandas code (schema `StepDraft`). The sandbox runs it on a copy of the current version and the
Cleaner's verifiers check the result. A failure goes back to the model once (the client's repair), then the
answer says why. What passes is stored as a `clean_step` (or `computed_column`) proposal. Its card shows the code
and the effect, written by code from the diff, never by the model.

OK (approve) runs the stored code again on the version that is current then: same effect, saved as one step
(`created_by="chat"`, undoable, replayed and exported like the Cleaner's steps). A different effect refreshes the
card for one more OK. While a clean runs, OK queues the step, and the job applies it when it ends.
Rows are never deleted: a request to delete rows sets them aside (`quarantine_rows`).
"""

import json
import re
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd

from sherlock.agent import prompts
from sherlock.agent.answerers import CantAnswer, Toolkit
from sherlock.cleaning import verifiers
from sherlock.cleaning.prompts import HELPERS
from sherlock.db.util import new_id, now_iso
from sherlock.errors import ApiError
from sherlock.jobs.events import emit
from sherlock.llm.client import StructuredOutputError, fence
from sherlock.llm.schemas import StepDraft
from sherlock.llm.wording import wording_problem
from sherlock.query import context as qx
from sherlock.query.context import Env
from sherlock.sandbox import runner as sandbox
from sherlock.sandbox.static_check import check as static_check
from sherlock.steps.commit import Context, StepSpec, commit_step
from sherlock.steps.diff import check_version_file, diff_versions
from sherlock.storage import dataset_dir, sql_path

KINDS = ("clean_step", "computed_column")
SYSTEM_COLUMNS = ("_row_id", "_quarantine_reason")
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_ ]{0,62}$")
# The hard checks the card shows, in the user's words (all of them passed, or there's no card).
CHECK_WORDS = {"row_ledger": "no rows lost", "nan_introduced": "no new blanks", "dtype": "column types kept",
               "placeholder_fill": "no placeholder fills", "merge_safety": "no distinct values merged",
               "parse_quarantine": "unreadable values set aside"}


class StepFailed(Exception):
    """The code failed to run, or its result failed a check; the message says why, in plain words."""


@dataclass
class DryRun:
    out: Path
    impact: dict
    before_after: list[dict]
    report: verifiers.Report
    columns_changed: list[str]
    warnings: list[str]


def plain(code: str) -> str:
    """The code with its line breaks: live, Nemotron sometimes sends them escaped (a backslash, then "n") inside the
    JSON string, which reads as one line the parser refuses."""
    if "\n" not in code.strip() and "\\n" in code:
        code = code.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "    ")
    return code


def full_code(code: str, rows: list[int] | None) -> str:
    """The code as it runs: the model's, limited to the selected rows when there are some."""
    lines = [code.rstrip()]
    if rows is not None:
        lines.append(f"result = keep_outside_scope(df, result, rows={sorted(rows)!r})")
    return "\n".join(lines) + "\n"


def notebook_code(code: str, rows: list[int] | None) -> str:
    return full_code(code, rows) + "df = result\n"


def _read(path: Path) -> pd.DataFrame:
    conn = duckdb.connect(":memory:")
    try:
        return conn.execute(f"SELECT * FROM read_parquet({sql_path(path)}) ORDER BY _row_id").df()
    finally:
        conn.close()


def _first_failure(report: verifiers.Report) -> str:
    for name, value in report.hard.items():
        if value != "pass":
            return f"{name.replace('_', ' ')}: {value.removeprefix('fail: ')}"
    return "a check failed"


def version_path(env: Env, dataset: sqlite3.Row, version: int) -> Path:
    vrow = qx.version_row(env.db, dataset["id"], version)
    return dataset_dir(env.settings, dataset["user_id"], dataset["id"]) / vrow["parquet_path"]


def dry_run(env: Env, dataset: sqlite3.Row, version: int, code: str, rows: list[int] | None,
            new_columns: list[str]) -> DryRun:
    """Run the code on a copy of `version` and check the result. The output file is the caller's to use or remove."""
    src = version_path(env, dataset, version)
    out = src.parent / f".chat_{uuid.uuid4().hex}.parquet"
    r = sandbox.execute(env.settings, full_code(code, rows), src, out, db=env.db, dataset_id=dataset["id"])
    if not r.ok:
        out.unlink(missing_ok=True)
        said = "; ".join(r.violations) if r.violations else (r.error or "unknown error")
        raise StepFailed(f"the code failed: {said}")
    try:
        check_version_file(out)
        diff = diff_versions(src, out)
        if diff.added_row_ids or diff.deleted_row_ids:
            raise StepFailed("it added or removed rows; rows are set aside with quarantine_rows, never removed")
        if diff.columns_removed:
            raise StepFailed(f"it removed columns ({', '.join(diff.columns_removed[:5])}); a command never removes columns")
        unexpected = sorted(set(diff.columns_added) - set(new_columns))
        if unexpected:
            raise StepFailed(f"it added columns that new_columns doesn't list ({', '.join(unexpected[:5])})")
        before, after = _read(src), _read(out)
        report = verifiers.verify(before, after[[c for c in after.columns if c not in diff.columns_added]], None, None,
                                  requested=True)
        # The user sees how many rows a command sets aside before pressing OK, so the Cleaner's cap (a fifth of
        # the rows) becomes a warning on the card instead of a refusal.
        wide = report.hard.get("quarantine_scope", "pass") != "pass"
        if wide:
            report.hard["quarantine_scope"] = "pass"
        if not report.passed:
            raise StepFailed(f"its result failed a check ({_first_failure(report)})")
        if new_columns:
            added = after[new_columns]
            if added.isna().all().any():
                empty = [c for c in new_columns if added[c].isna().all()]
                raise StepFailed(f"the new column {empty[0]} is empty in every row")
    except Exception:
        out.unlink(missing_ok=True)
        raise
    cells = [t for t in diff.lineage if t[1] != "_row"]
    changed_cols = list(dict.fromkeys(t[1] for t in cells if t[1] not in diff.columns_added))
    impact = {"cells_changed": len([t for t in cells if t[1] not in diff.columns_added]),
              "rows_affected": len({t[0] for t in diff.lineage}),
              "quarantined": report.quarantined, "columns_added": list(diff.columns_added)}
    if not (impact["cells_changed"] or impact["quarantined"] or impact["columns_added"]):
        out.unlink(missing_ok=True)
        raise StepFailed("it changes nothing in this version of the file")
    warnings = [f"This sets aside {report.quarantined:,} of {len(before):,} rows. Check that's what you meant before you "
                "press OK."] if wide else []
    return DryRun(out, impact, diff.before_after, report, changed_cols, warnings)


def summary(impact: dict, changed: list[str], rows: list[int] | None) -> str:
    """What the step does, from its counts (never the model's words)."""
    parts = []
    if impact["columns_added"]:
        parts.append(f"Add {'column' if len(impact['columns_added']) == 1 else 'columns'} {', '.join(impact['columns_added'])}")
    n, m = impact["cells_changed"], impact["rows_affected"]
    if n:
        parts.append(f"Change {n:,} {'cell' if n == 1 else 'cells'} in {m:,} {'row' if m == 1 else 'rows'}: {', '.join(changed)}")
    q = impact["quarantined"]
    if q:
        parts.append(f"Set aside {q:,} {'row' if q == 1 else 'rows'} (quarantined, not deleted)")
    text = " · ".join(parts)
    return text + (f" · on {len(rows):,} selected {'row' if len(rows) == 1 else 'rows'}" if rows is not None else "")


def _payload(code: str, columns: list[str], new_columns: list[str], rows: list[int] | None, run: DryRun) -> dict:
    return {"summary": summary(run.impact, run.columns_changed, rows), "code": code, "columns": columns,
            "new_columns": new_columns, "scope": {"row_ids": rows}, "impact": run.impact,
            "before_after": run.before_after, "warnings": run.warnings,
            "checks": [CHECK_WORDS[k] for k, v in run.report.hard.items() if k in CHECK_WORDS and v == "pass"]}


def scope_rows(env: Env, dataset: sqlite3.Row, context: dict) -> list[int] | None:
    """The `_row_id`s the command is limited to: the selected cells' rows, else the selection's on the current
    version, else None (every row)."""
    cells = context.get("selected_cells") or {}
    rows = [int(r) for r in cells.get("row_ids") or [] if isinstance(r, int | float)]
    if rows:
        return sorted(set(rows))
    sel = context.get("selection_id")
    if not sel:
        return None
    where = qx.selection_sql(env.db, dataset["id"], sel)
    with qx.connection(env, dataset, dataset["current_version"]) as conn:
        return [r[0] for r in conn.execute(f"SELECT _row_id FROM t WHERE {where} ORDER BY _row_id").fetchall()]  # noqa: S608


def propose(kit: Toolkit, question: str, context: dict, types: dict[str, str]) -> dict:
    """`clean_step`: the code, its dry run and the card. A request the model can't turn into a safe change
    is answered with the reason (CantAnswer), never a card."""
    env, dataset = kit.env, kit.dataset
    rows = scope_rows(env, dataset, context)
    if rows is not None and not rows:
        raise CantAnswer("The selection holds no rows in this version of the file, so there's nothing to change.")
    got: dict = {}

    def check(d: StepDraft) -> None:
        if not d.doable:
            return
        unknown = [c for c in d.columns if c not in types and c not in d.new_columns]
        if unknown:
            raise ValueError(f"{unknown[0]!r} is not a column of this file; use one of {', '.join(list(types)[:40])}")
        for c in d.new_columns:
            if c in types or c in SYSTEM_COLUMNS or not NAME.match(c):
                raise ValueError(f"{c!r} can't be a new column: it exists already or isn't a plain name")
        d.code = plain(d.code)
        problems = static_check(d.code)
        if problems:
            raise ValueError("the sandbox refuses this code: " + "; ".join(str(p) for p in problems[:3]))
        old = got.pop("run", None)
        if old is not None:
            old.out.unlink(missing_ok=True)
        try:
            got["run"] = dry_run(env, dataset, dataset["current_version"], d.code, rows, list(d.new_columns))
        except StepFailed as exc:
            raise ValueError(f"When the code ran on the file, {exc}. Fix the code.") from None

    where = (f"The request is about {len(rows):,} selected rows: write the code for every row, and code limits the "
             "change to the selection.\n") if rows is not None else ""
    dtypes = "\n".join(f"- {c}: {t}" for c, t in types.items())
    messages = [{"role": "system", "content": prompts.SYSTEM},
                {"role": "user", "content": prompts.STEP.format(context=kit.context, dtypes=fence(dtypes), helpers=HELPERS,
                                                                scope=where, message=fence(question))}]
    try:
        draft = kit.llm.structured("medium", messages, StepDraft, purpose="step", scope=kit.scope, validate=check).value
    except StructuredOutputError as exc:
        why = str(exc).split(": ", 1)[-1]
        why = re.sub(r"^When the code ran on the file, ", "", why).removesuffix(". Fix the code.")
        raise CantAnswer(f"I couldn't write a safe change for that: {why[:300]}") from None
    if not draft.doable:
        said = draft.reading.strip()
        raise CantAnswer("I can't make that change to this file" + (f": {said}" if said and not wording_problem(said) else "."))
    run = got["run"]
    try:
        payload = {**_payload(draft.code, list(draft.columns), list(draft.new_columns), rows, run), "asked": question[:300]}
    finally:
        run.out.unlink(missing_ok=True)
    kind = "computed_column" if draft.new_columns else "clean_step"
    pid = new_id("prp")
    env.db.execute("INSERT INTO proposals (id, dataset_id, message_id, kind, base_version, payload_json, status, created_at) "
                   "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
                   (pid, dataset["id"], kit.scope.message_id, kind, dataset["current_version"], json.dumps(payload, default=str),
                    now_iso()))
    from sherlock.agent.actions import to_proposal

    return to_proposal(env.db.execute("SELECT * FROM proposals WHERE id = ?", (pid,)).fetchone())


def then(db: sqlite3.Connection, proposal: dict, questions: list[str]) -> dict:
    """The rest of a message that asked for a change and then something else ("fix fare, then the average fare by
    class"): stored on the card, and the app sends it as the next message once the user presses OK."""
    from sherlock.agent.actions import to_proposal

    row = db.execute("SELECT * FROM proposals WHERE id = ?", (proposal["id"],)).fetchone()
    payload = {**json.loads(row["payload_json"]), "then": " and ".join(q.strip().rstrip("?.") for q in questions) + "?"}
    db.execute("UPDATE proposals SET payload_json = ? WHERE id = ?", (json.dumps(payload, default=str), proposal["id"]))
    return to_proposal(db.execute("SELECT * FROM proposals WHERE id = ?", (proposal["id"],)).fetchone())


def _same(a: dict, b: dict) -> bool:
    return all(a.get(k) == b.get(k) for k in ("cells_changed", "rows_affected", "quarantined", "columns_added"))


def run(env: Env, dataset: sqlite3.Row, row: sqlite3.Row) -> dict:
    """OK: run the stored code on the current version. `{ step, version }` when saved, `{ refreshed: proposal }`
    when the data changed since the card and the effect differs, `{ queued: proposal }` while a clean runs."""
    from sherlock.agent.actions import to_proposal

    db = env.db
    payload = json.loads(row["payload_json"])
    if dataset["status"] == "cleaning":  # `resolved_at` keeps the order of the OKs
        db.execute("UPDATE proposals SET status = 'queued', resolved_at = ? WHERE id = ?", (now_iso(), row["id"]))
        return {"queued": to_proposal(db.execute("SELECT * FROM proposals WHERE id = ?", (row["id"],)).fetchone())}
    version = dataset["current_version"]
    rows = (payload.get("scope") or {}).get("row_ids")
    try:
        dr = dry_run(env, dataset, version, payload["code"], rows, payload.get("new_columns") or [])
    except StepFailed as exc:
        db.execute("UPDATE proposals SET status = 'failed', resolved_at = ?, payload_json = ? WHERE id = ?",
                   (now_iso(), json.dumps({**payload, "error": str(exc)}, default=str), row["id"]))
        raise ApiError(409, "conflict", f"Couldn't run it on version {version}: {exc}. Nothing changed.") from None
    try:
        if version != row["base_version"] and not _same(dr.impact, payload["impact"]):
            fresh = {**_payload(payload["code"], payload["columns"], payload.get("new_columns") or [], rows, dr),
                     "asked": payload.get("asked"), "rechecked_on": version}
            db.execute("UPDATE proposals SET base_version = ?, payload_json = ?, status = 'pending' WHERE id = ?",
                       (version, json.dumps(fresh, default=str), row["id"]))
            return {"refreshed": to_proposal(db.execute("SELECT * FROM proposals WHERE id = ?", (row["id"],)).fetchone())}
        kind = "computed_column" if payload.get("new_columns") else "clean"
        spec = StepSpec(kind=kind, summary=summary(dr.impact, dr.columns_changed, rows), created_by="chat",
                        notebook_code=notebook_code(payload["code"], rows), code=full_code(payload["code"], rows),
                        column_targets=list(dict.fromkeys(list(payload["columns"]) + dr.impact["columns_added"])),
                        gate="user", parse_failures=dr.report.quarantined, verifiers=dr.report.as_json(),
                        decisions=[{"question": "What did you ask for?", "chosen": "the code shown in chat",
                                    "alternatives": [], "reason": "you pressed OK", "asked": payload.get("asked") or ""}])
        ctx = Context(env.settings, db, env.cache, env.bus)
        step, new_version = commit_step(ctx, dataset["id"], version, spec, lambda _old, out: shutil.copyfile(dr.out, out))
    finally:
        dr.out.unlink(missing_ok=True)
    db.execute("UPDATE proposals SET status = 'approved', result_step_id = ?, resolved_at = ? WHERE id = ?",
               (step["id"], now_iso(), row["id"]))
    return {"step": step, "version": new_version}


def run_queued(env: Env, dataset_id: str) -> list[str]:
    """After a clean ends (or is stopped): the commands OK'd while it ran, in the order of their OK, each on the
    version the one before left. Returns what happened to each, for the log."""
    out = []
    queued = env.db.execute("SELECT * FROM proposals WHERE dataset_id = ? AND status = 'queued' ORDER BY resolved_at, rowid",
                            (dataset_id,)).fetchall()
    for row in queued:
        dataset = env.db.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
        env.db.execute("UPDATE proposals SET status = 'pending' WHERE id = ?", (row["id"],))
        try:
            got = run(env, dataset, env.db.execute("SELECT * FROM proposals WHERE id = ?", (row["id"],)).fetchone())
            out.append(f"saved as v{got['version']}" if "version" in got else "the data changed: check the card again")
        except ApiError as exc:
            out.append(exc.message)
        emit(env.db, env.bus, dataset_id, dataset["user_id"], "chat.updated", {})  # the card reads its new state
    return out
