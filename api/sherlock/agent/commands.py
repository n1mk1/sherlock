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
import time
import uuid
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import pandas as pd
from rapidfuzz import fuzz, process, utils

from sherlock.agent import prompts
from sherlock.agent.answerers import CantAnswer, Toolkit
from sherlock.cleaning import verifiers
from sherlock.cleaning.helpers import _merge_key, _merge_refusal
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


# What a refused check says to the user (all of it written here, never by the model): what the code would have done,
# and what to say instead. `{n}` is a count from the report.
REFUSED = {
    "row_ledger": "The code would add or lose rows, and a command never does that. To get rows out of the way, say "
                  "'delete the rows where …' and I'll set them aside.",
    "dtype": "The code would leave text mixed in with numbers or dates in one column. Say what the column should hold, "
             "for example 'make fare a number'.",
    "parse_quarantine": "The code leaves {n} values it couldn't read as the new type. Ask me to set the ones that don't "
                        "convert aside as well.",
    "pandera": "The code would break the file's structure (its row numbers or set-aside marks).",
}
SAID = {
    "removed": "The code would remove {cols}, and a command never removes a column.",
    "extra": "The code would add a column you didn't ask for ({cols}). To add one, say 'add a column …'.",
    "empty": "The new column {col} would be empty in every row. Say how its values are worked out, for example "
             "'add total = price * quantity'.",
    "name": "I can't add a column called {col}: the name is taken or isn't a plain name. Say what to call it, using "
            "letters, digits and underscores.",
    "nothing": "Nothing in this version matches that, so there's nothing to change.",
    "crash": "The code I wrote didn't run. Try naming the column and what to do with it.",
    "crash_column": "The code I wrote didn't run (it looked for a column that isn't there). Try naming the column.",
    "slow": "The code I wrote took too long on this file, so I stopped it. Try a smaller change.",
    "refused": "The code I wrote tried something a command isn't allowed to do. Try saying it another way.",
    "default": "I couldn't turn that into a change I could check. Try naming the column and what to do with it.",
}


class StepFailed(Exception):
    """The code failed to run, or its result failed a check. `str(exc)` says why, for the model (the repair
    message); `exc.user` says it to the user in plain words, with what to do next."""

    def __init__(self, why: str, user: str = ""):
        super().__init__(why)
        self.user = user or SAID["default"]


def no_column(name: str, columns: list[str]) -> str:
    """"This file has no column called Fare. The closest are fare and fare_usd." (closest by rapidfuzz)"""
    close = [c for c, _, _ in process.extract(name, [c for c in columns if c not in SYSTEM_COLUMNS], scorer=fuzz.WRatio,
                                              processor=utils.default_process, score_cutoff=70, limit=2)]
    return f"This file has no column called {name}." + (f" The closest {'is' if len(close) == 1 else 'are'} "
                                                        f"{' and '.join(close)}." if close else "")


@dataclass
class DryRun:
    out: Path
    impact: dict
    before_after: list[dict]
    report: verifiers.Report
    columns_changed: list[str]
    warnings: list[str]
    warned: list[str] = field(default_factory=list)  # checks that failed but became warnings: the card shows no tick for them
    seconds: dict = field(default_factory=dict)      # {"sandbox": …, "checks": …}, for the timing log


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


def _refusal(report: verifiers.Report, skip: list[str] = ()) -> StepFailed:
    """The first failed check that is not a warning, as a StepFailed: the model's text and the user's sentence."""
    for name, value in report.hard.items():
        if value != "pass" and name not in skip:
            return StepFailed(f"its result failed a check ({name.replace('_', ' ')}: {value.removeprefix('fail: ')})",
                              REFUSED.get(name, SAID["default"]).format(n=report.parse_failures))
    return StepFailed("a check failed")


def version_path(env: Env, dataset: sqlite3.Row, version: int) -> Path:
    vrow = qx.version_row(env.db, dataset["id"], version)
    return dataset_dir(env.settings, dataset["user_id"], dataset["id"]) / vrow["parquet_path"]


def _crash(r: sandbox.SandboxResult, src: Path) -> str:
    """A failed run in plain words: no exception name. A key the file doesn't have gets the closest columns."""
    if r.violations:
        return SAID["refused"]
    if r.timed_out:
        return SAID["slow"]
    named = re.match(r"KeyError: ['\"](.+)['\"]$", r.error or "")
    if named:
        with closing(duckdb.connect(":memory:")) as conn:
            columns = [row[0] for row in conn.execute(f"DESCRIBE SELECT * FROM read_parquet({sql_path(src)})").fetchall()]
        return no_column(named.group(1), columns) if named.group(1) not in columns else SAID["crash_column"]
    return SAID["crash"]


def _s(n: int, one: str, many: str) -> str:
    return f"{n:,} {one if n == 1 else many}"


def _warned(report: verifiers.Report, before: pd.DataFrame, after: pd.DataFrame) -> dict[str, list[str]]:
    """The checks the user's request outranks (R4): a failed `nan_introduced`, `placeholder_fill`, `merge_safety`, or
    a number or date column turned into text. Each becomes card warnings, one per column, counted here from the two
    frames by the verifiers' own rules. A check with no count to show stays a refusal."""
    failed = {k for k in ("nan_introduced", "placeholder_fill", "merge_safety", "dtype") if report.hard.get(k, "pass") != "pass"}
    if not failed:
        return {}
    b = before.set_index("_row_id")
    a = after.set_index("_row_id").reindex(b.index)
    shut = a["_quarantine_reason"].notna() & b["_quarantine_reason"].isna()
    out: dict[str, list[str]] = {k: [] for k in failed}
    user = [c for c in b.columns if c not in SYSTEM_COLUMNS]
    for c in user:
        bc, ac = b[c], a[c]
        if "nan_introduced" in failed:
            n = int((bc.notna() & ac.isna() & ~(verifiers._is_placeholder(bc) | shut)).sum())
            if n:
                out["nan_introduced"].append(f"This empties {_s(n, 'cell that had a value', 'cells that had values')}, in {c}.")
        if "placeholder_fill" in failed:
            filled = ac[bc.isna() & ac.notna()]
            words = filled[filled.map(lambda v: isinstance(v, str) and v.strip().lower() in verifiers.PLACEHOLDER_WORDS)]
            if len(words):
                out["placeholder_fill"].append(f"This fills {_s(len(words), 'blank', 'blanks')} in {c} with the text "
                                               f"'{words.mode().iloc[0]}'. Sherlock can't tell that apart from a real value.")
        if "merge_safety" in failed and bc.dtype == object and ac.dtype == object:
            rewritten = bc.notna() & ac.notna() & (bc.astype(str) != ac.astype(str))
            counts = bc.dropna().astype(str).map(_merge_key).value_counts().to_dict()
            merged: set = set()
            for old, new in pd.DataFrame({"old": bc[rewritten], "new": ac[rewritten]}).drop_duplicates().itertuples(index=False):
                if (isinstance(old, str) and isinstance(new, str) and _merge_key(new) in counts
                        and _merge_refusal(old, new, counts, len(b))):
                    merged |= {old, new}
            if merged:
                out["merge_safety"].append(f"This makes {len(merged):,} different values in {c} the same value.")
        if "dtype" in failed and bc.dtype.kind in "iufM" and ac.dtype == object and not ac.dropna().empty:
            out["dtype"].append(f"{c} becomes text: sorting and sums on it will stop working.")
    if "dtype" in failed and any(verifiers._mixed(a[c]) and not verifiers._mixed(b[c]) for c in user):
        out["dtype"] = []  # mixed types break the file and the grid: a refusal
    return {k: v for k, v in out.items() if v}


def dry_run(env: Env, dataset: sqlite3.Row, version: int, code: str, rows: list[int] | None,
            new_columns: list[str]) -> DryRun:
    """Run the code on a copy of `version` and check the result. The output file is the caller's to use or remove.
    Each file is read once, into a throwaway DuckDB that the diff and the verifiers share."""
    src = version_path(env, dataset, version)
    out = src.parent / f".chat_{uuid.uuid4().hex}.parquet"
    t0 = time.perf_counter()
    r = sandbox.execute(env.settings, full_code(code, rows), src, out, db=env.db, dataset_id=dataset["id"])
    seconds = {"sandbox": round(time.perf_counter() - t0, 3)}
    if not r.ok:
        out.unlink(missing_ok=True)
        said = "; ".join(r.violations) if r.violations else (r.error or "unknown error")
        raise StepFailed(f"the code failed: {said}", _crash(r, src))
    t0 = time.perf_counter()
    try:
        try:
            check_version_file(out)
        except ValueError as exc:  # the code touched _row_id or dropped a system column
            raise StepFailed(str(exc), REFUSED["pandera"]) from None
        with closing(duckdb.connect(":memory:")) as conn:
            for name, path in (("o", src), ("n", out)):
                conn.execute(f"CREATE TABLE {name} AS SELECT * FROM read_parquet({sql_path(path)})")
            diff = diff_versions(src, out, conn)
            if diff.added_row_ids or diff.deleted_row_ids:
                raise StepFailed("it added or removed rows; rows are set aside with quarantine_rows, never removed",
                                 REFUSED["row_ledger"])
            if diff.columns_removed:
                raise StepFailed(f"it removed columns ({', '.join(diff.columns_removed[:5])}); a command never removes columns",
                                 SAID["removed"].format(cols=", ".join(diff.columns_removed[:5])))
            unexpected = sorted(set(diff.columns_added) - set(new_columns))
            if unexpected:
                raise StepFailed(f"it added columns that new_columns doesn't list ({', '.join(unexpected[:5])})",
                                 SAID["extra"].format(cols=", ".join(unexpected[:5])))
            before, after = (conn.execute(f"SELECT * FROM {t} ORDER BY _row_id").df() for t in ("o", "n"))
        report = verifiers.verify(before, after[[c for c in after.columns if c not in diff.columns_added]], None, None,
                                  requested=True)
        # The user sees how many rows a command sets aside before pressing OK, so the Cleaner's cap (a fifth of
        # the rows) becomes a warning on the card instead of a refusal.
        wide = report.hard.get("quarantine_scope", "pass") != "pass"
        if wide:
            report.hard["quarantine_scope"] = "pass"
        # The same for what the user's own request explains: the report keeps the failure, the card says it.
        said = _warned(report, before, after)
        if any(v != "pass" and k not in said for k, v in report.hard.items()):
            raise _refusal(report, list(said))
        if new_columns:
            added = after[new_columns]
            if added.isna().all().any():
                empty = [c for c in new_columns if added[c].isna().all()]
                raise StepFailed(f"the new column {empty[0]} is empty in every row", SAID["empty"].format(col=empty[0]))
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
        raise StepFailed("it changes nothing in this version of the file", SAID["nothing"])
    warnings = [f"This sets aside {report.quarantined:,} of {len(before):,} rows. Check that's what you meant before you "
                "press OK."] if wide else []
    for lines in said.values():
        warnings += lines[:5] + ([f"The same happens in {len(lines) - 5} more columns."] if len(lines) > 5 else [])
    seconds["checks"] = round(time.perf_counter() - t0, 3)
    return DryRun(out, impact, diff.before_after, report, changed_cols, warnings, list(said), seconds)


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
            "checks": [CHECK_WORDS[k] for k, v in run.report.hard.items()
                       if k in CHECK_WORDS and v == "pass" and k not in run.warned]}


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
            got["said"] = no_column(unknown[0], list(types))
            raise ValueError(f"{unknown[0]!r} is not a column of this file; use one of {', '.join(list(types)[:40])}")
        for c in d.new_columns:
            if c in types or c in SYSTEM_COLUMNS or not NAME.match(c):
                got["said"] = SAID["name"].format(col=c)
                raise ValueError(f"{c!r} can't be a new column: it exists already or isn't a plain name")
        d.code = plain(d.code)
        problems = static_check(d.code)
        if problems:
            got["said"] = SAID["refused"]
            raise ValueError("the sandbox refuses this code: " + "; ".join(str(p) for p in problems[:3]))
        old = got.pop("run", None)
        if old is not None:
            old.out.unlink(missing_ok=True)
        try:
            got["run"] = dry_run(env, dataset, dataset["current_version"], d.code, rows, list(d.new_columns))
        except StepFailed as exc:
            got["said"] = exc.user
            raise ValueError(f"When the code ran on the file, {exc}. Fix the code.") from None

    def validate(d: StepDraft) -> None:  # `got["said"]` is the user's text for the last failure only
        got.pop("said", None)
        check(d)

    where = (f"The request is about {len(rows):,} selected rows: write the code for every row, and code limits the "
             "change to the selection.\n") if rows is not None else ""
    dtypes = "\n".join(f"- {c}: {t}" for c, t in types.items())
    messages = [{"role": "system", "content": prompts.SYSTEM},
                {"role": "user", "content": prompts.STEP.format(context=kit.context, dtypes=fence(dtypes), helpers=HELPERS,
                                                                scope=where, message=fence(question))}]
    try:
        draft = kit.llm.structured("medium", messages, StepDraft, purpose="step", scope=kit.scope, validate=validate).value
    except StructuredOutputError:
        raise CantAnswer(got.get("said") or SAID["default"]) from None
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
    parts = [q.strip() for q in questions if q.strip()]  # as typed: no "and" and no "?" added to the user's words
    text = " ".join(q if q[-1] in ".?!" or i == len(parts) - 1 else q + "." for i, q in enumerate(parts))
    payload = {**json.loads(row["payload_json"]), "then": text}
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
        raise ApiError(409, "conflict", f"Couldn't run it on version {version}. {exc.user} Nothing changed.") from None
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
