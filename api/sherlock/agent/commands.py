"""Cleaning commands typed in chat (docs/plans/chat-commands.md): "trim the spaces in name", "make fare a number",
"add family_size = sibsp + parch", "delete the rows with no age".

`medium` writes pandas code (schema `StepDraft`). The sandbox runs it on a copy of the current version and the
Cleaner's verifiers check the result. A failure goes back to the model once (the client's repair), then the
answer says why. What passes is stored as a `clean_step` (or `computed_column`) proposal. Its card shows the code
and the effect, written by code from the diff, never by the model.

OK (approve) saves the dry run's file when the version hasn't moved since the card (kept as
`.chat_<proposal id>.parquet`, no second sandbox run). When it has moved, OK runs the stored code again on the
version that is current then: same effect, saved as one step (`created_by="chat"`, undoable, replayed and exported
like the Cleaner's steps). A different effect refreshes the card for one more OK, with the new run kept. A kept file
is removed on Cancel, on failure, after the commit, when OK finds the version moved, and at startup when its card
isn't waiting. While a clean runs, OK queues the step, and the job applies it when it ends.
Rows are never deleted: a request to delete rows sets them aside (`quarantine_rows`).
"""

import json
import logging
import re
import shutil
import sqlite3
import time
import uuid
from collections.abc import Callable
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
from sherlock.sandbox.static_check import style as code_style
from sherlock.steps.commit import Context, StepSpec, commit_step
from sherlock.steps.diff import NUMBER, check_version_file, diff_versions
from sherlock.storage import dataset_dir, sql_path

log = logging.getLogger("sherlock.agent")
KINDS = ("clean_step", "computed_column")
SYSTEM_COLUMNS = ("_row_id", "_quarantine_reason")
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_ ]{0,62}$")
THEN = re.compile(r"\s*[,;.]?\s+(?:and\s+)?then\s+", re.I)  # where "round fare, then count by sex" splits
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
    out = kept_file(env.settings, dataset["user_id"], dataset["id"], uuid.uuid4().hex)  # where the startup sweep looks
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
            added = after.reindex(columns=new_columns)  # a listed column the code didn't add is empty too
            if added.isna().all().any():
                empty = [c for c in new_columns if added[c].isna().all()]
                raise StepFailed(f"the new column {empty[0]} is empty in every row", SAID["empty"].format(col=empty[0]))
    except Exception:
        out.unlink(missing_ok=True)
        raise
    cells = [t for t in diff.lineage if t[1] != "_row"]
    changed_cols = list(dict.fromkeys(t[1] for t in cells if t[1] not in diff.columns_added))
    # A new type is an effect of its own: "make age a whole number" on 22.0, 30.0 changes no value, only the type.
    retyped = {c: holds(new) for c, (old, new) in diff.retyped.items() if holds(old) != holds(new)}
    impact = {"cells_changed": len([t for t in cells if t[1] not in diff.columns_added]),
              "rows_affected": len({t[0] for t in diff.lineage}),
              "quarantined": report.quarantined, "columns_added": list(diff.columns_added),
              **({"columns_retyped": retyped} if retyped else {})}
    if not (impact["cells_changed"] or impact["quarantined"] or impact["columns_added"] or retyped):
        out.unlink(missing_ok=True)
        raise StepFailed("it changes nothing in this version of the file", SAID["nothing"])
    warnings = [f"This sets aside {report.quarantined:,} of {len(before):,} rows. Check that's what you meant before you "
                "press OK."] if wide else []
    for lines in said.values():
        warnings += lines[:5] + ([f"The same happens in {len(lines) - 5} more columns."] if len(lines) > 5 else [])
    seconds["checks"] = round(time.perf_counter() - t0, 3)
    return DryRun(out, impact, diff.before_after, report, changed_cols, warnings, list(said), seconds)


def holds(duck_type: str) -> str:
    """What a column of this DuckDB type holds, in plain words: "whole numbers", "text"."""
    t = duck_type.upper()
    if t.startswith(NUMBER):
        return "whole numbers" if "INT" in t else "numbers"
    return next((w for p, w in (("VARCHAR", "text"), ("TIMESTAMP", "dates with times"), ("DATE", "dates"), ("TIME", "times"),
                                ("BOOLEAN", "true or false values"), ("INTERVAL", "durations")) if t.startswith(p)), t.lower())


def summary(impact: dict, changed: list[str], rows: list[int] | None) -> str:
    """What the step does, from its counts and types (never the model's words)."""
    parts = []
    if impact["columns_added"]:
        parts.append(f"Add {'column' if len(impact['columns_added']) == 1 else 'columns'} {', '.join(impact['columns_added'])}")
    retyped = impact.get("columns_retyped") or {}
    for words in dict.fromkeys(retyped.values()):  # "Make age whole numbers"
        parts.append(f"Make {', '.join(c for c, w in retyped.items() if w == words)} {words}")
    n, m = impact["cells_changed"], impact["rows_affected"]
    if n:
        parts.append(f"Change {n:,} {'cell' if n == 1 else 'cells'} in {m:,} {'row' if m == 1 else 'rows'}: {', '.join(changed)}")
    q = impact["quarantined"]
    if q:
        parts.append(f"Set aside {q:,} {'row' if q == 1 else 'rows'} (quarantined, not deleted)")
    text = " · ".join(parts)
    return text + (f" · on {len(rows):,} selected {'row' if len(rows) == 1 else 'rows'}" if rows is not None else "")


def _payload(code: str, columns: list[str], new_columns: list[str], rows: list[int] | None, run: DryRun,
             reading: str = "") -> dict:
    """The card. `kept` is what OK needs to commit the kept dry run without running it again (not sent to the app)."""
    return {"summary": summary(run.impact, run.columns_changed, rows), "reading": reading, "code": code, "columns": columns,
            "new_columns": new_columns, "scope": {"row_ids": rows}, "impact": run.impact,
            "before_after": run.before_after, "warnings": run.warnings,
            "checks": [CHECK_WORDS[k] for k, v in run.report.hard.items()
                       if k in CHECK_WORDS and v == "pass" and k not in run.warned],
            "kept": {"columns_changed": run.columns_changed, "verifiers": run.report.as_json(),
                     "quarantined": run.report.quarantined}}


def _reading_problem(reading: str) -> str | None:
    """Why the model's reading can't be shown: empty, a digit, or a wording rule (numbers come from code)."""
    said = reading.strip()
    return "it is empty" if not said else "it has a digit" if re.search(r"\d", said) else wording_problem(said)


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


def kept_file(settings, user_id: str, dataset_id: str, proposal_id: str) -> Path:
    """Where a card keeps its passing dry run, next to the dataset's version files."""
    return dataset_dir(settings, user_id, dataset_id) / f".chat_{proposal_id}.parquet"


def discard(settings, db: sqlite3.Connection, row: sqlite3.Row) -> None:
    """Remove the card's kept dry run (Cancel)."""
    ds = db.execute("SELECT user_id FROM datasets WHERE id = ?", (row["dataset_id"],)).fetchone()
    if ds:
        kept_file(settings, ds["user_id"], row["dataset_id"], row["id"]).unlink(missing_ok=True)


def sweep(settings, db: sqlite3.Connection) -> int:
    """At startup: remove every `.chat_*` file under the data folder whose card isn't waiting for OK (a card
    decided while the app was down, or a dry run that was cut off). A glob, nothing per dataset."""
    files = list((settings.data_dir / "users").glob("*/datasets/*/.chat_*"))
    if not files:
        return 0
    waiting = {r[0] for r in db.execute("SELECT id FROM proposals WHERE status IN ('pending', 'queued')")}
    gone = 0
    for f in files:
        if f.name.removeprefix(".chat_").removesuffix(".parquet") not in waiting:
            try:
                f.unlink()
                gone += 1
            except OSError:
                log.warning("couldn't remove %s", f)
    return gone


def examples(kit: Toolkit, question: str, types: dict[str, str]) -> str:
    """The `{dtypes}` lines: every column's type, and up to three values for the columns the question names."""
    q = question.lower()
    named = [c for c in types if c not in SYSTEM_COLUMNS and re.search(rf"(?<!\w){re.escape(c.lower())}(?!\w)", q)][:8]
    seen: dict[str, str] = {}
    if named:
        try:
            with qx.connection(kit.env, kit.dataset, kit.dataset["current_version"]) as conn:
                for c in named:
                    col = '"' + c.replace('"', '""') + '"'
                    vals = [str(v[0]).replace("\n", " ")[:30] for v in
                            conn.execute(f"SELECT DISTINCT {col} FROM t WHERE {col} IS NOT NULL LIMIT 3").fetchall()]  # noqa: S608
                    if vals:
                        seen[c] = ", ".join(vals)
        except Exception:  # the examples are a help, never a reason to fail
            log.warning("couldn't read example values", exc_info=True)
    return "\n".join(f"- {c}: {t}" + (f" (e.g. {seen[c]})" if c in seen else "") for c, t in types.items())


def propose(kit: Toolkit, question: str, context: dict, types: dict[str, str],
            status: Callable[[str], None] | None = None) -> dict:
    """`clean_step`: the code, its dry run and the card. A request the model can't turn into a safe change
    is answered with the reason (CantAnswer), never a card. `status` hears each stage in plain words."""
    env, dataset = kit.env, kit.dataset
    say = status or (lambda _text: None)
    rows = scope_rows(env, dataset, context)
    if rows is not None and not rows:
        raise CantAnswer("The selection holds no rows in this version of the file, so there's nothing to change.")
    got: dict = {}  # "run" only for a draft that passed every check, which ends the call: no failure holds a file

    def refuse(why: str, user: str) -> ValueError:
        """The error for the model's repair, with the user's sentence kept against it: the user sees it only when it
        is the last error (a reply that doesn't parse after it gets the default)."""
        got["said"] = (why, user)
        return ValueError(why)

    def check(d: StepDraft) -> None:
        got["drafts"] = got.get("drafts", 0) + 1
        if not d.doable:
            return
        bad = _reading_problem(d.reading)  # before the dry run, so a bad reading costs no sandbox run
        if bad:
            raise ValueError(f"reading must be one plain sentence saying what the code does, in the user's terms (for "
                             f"example 'Upper-case every value in sex'), with no digits and no causal words: {bad}. Fix the reading.")
        unknown = [c for c in d.columns if c not in types and c not in d.new_columns]
        if unknown:
            raise refuse(f"{unknown[0]!r} is not a column of this file; use one of {', '.join(list(types)[:40])}",
                         no_column(unknown[0], list(types)))
        for c in d.new_columns:
            if c in types or c in SYSTEM_COLUMNS or not NAME.match(c):
                raise refuse(f"{c!r} can't be a new column: it exists already or isn't a plain name", SAID["name"].format(col=c))
        d.code = plain(d.code)
        problems = static_check(d.code)
        if problems:
            raise refuse("the sandbox refuses this code: " + "; ".join(str(p) for p in problems[:3]), SAID["refused"])
        if got["drafts"] == 1 and (plain_it := code_style(d.code)):  # only the first draft is sent back for style
            raise ValueError("Write plainer code (no sandbox run yet): " + "; ".join(plain_it[:3]))
        if got["drafts"] > 1:
            say("Fixing the code")
        say("Running it on a copy of the file")
        try:
            got["run"] = dry_run(env, dataset, dataset["current_version"], d.code, rows, list(d.new_columns))
        except StepFailed as exc:
            raise refuse(f"When the code ran on the file, {exc}. Fix the code.", exc.user) from None

    where = (f"The request is about {len(rows):,} selected rows: write the code for every row, and code limits the "
             "change to the selection.\n") if rows is not None else ""
    dtypes = examples(kit, question, types)
    messages = [{"role": "system", "content": prompts.SYSTEM},
                {"role": "user", "content": prompts.STEP.format(context=kit.context, dtypes=fence(dtypes), helpers=HELPERS,
                                                                scope=where, message=fence(question))}]
    say("Writing the code")
    started = time.monotonic()
    try:
        draft = kit.llm.structured("medium", messages, StepDraft, purpose="step", scope=kit.scope, validate=check).value
    except StructuredOutputError as exc:
        why, user = got.get("said") or ("", "")  # the client keeps the error's first line, cut at 300 characters
        raise CantAnswer(user if why and str(exc).endswith(why.splitlines()[0][:300]) else SAID["default"]) from None
    if not draft.doable:
        said = draft.reading.strip()
        raise CantAnswer("I can't make that change to this file" + (f": {said}" if not _reading_problem(said) else "."))
    run = got["run"]
    pid = new_id("prp")
    log.info("command: model and checks %.1fs; dry run %s", time.monotonic() - started,
             {k: round(v, 2) for k, v in run.seconds.items()})
    try:  # the passing dry run stays as the card's file: OK commits it if the version hasn't moved
        payload = {**_payload(draft.code, list(draft.columns), list(draft.new_columns), rows, run, draft.reading.strip()),
                   "asked": question[:300]}
        run.out.replace(kept_file(env.settings, dataset["user_id"], dataset["id"], pid))
    finally:
        run.out.unlink(missing_ok=True)
    kind = "computed_column" if draft.new_columns else "clean_step"
    env.db.execute("INSERT INTO proposals (id, dataset_id, message_id, kind, base_version, payload_json, status, created_at) "
                   "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
                   (pid, dataset["id"], kit.scope.message_id, kind, dataset["current_version"], json.dumps(payload, default=str),
                    now_iso()))
    from sherlock.agent.actions import to_proposal

    return to_proposal(env.db.execute("SELECT * FROM proposals WHERE id = ?", (pid,)).fetchone())


def then(db: sqlite3.Connection, proposal: dict, questions: list[str], message: str = "", done: int = 1) -> dict:
    """The rest of a message that asked for a change and then something else ("fix fare, then the average fare by
    class"): stored on the card, and the app sends it as the next message once the user presses OK. `done` is how many
    of the message's steps ran, the command included. When the message splits at its "then"s into as many parts as
    there are steps, the rest is the user's own words after the command's part; else the planner's questions."""
    from sherlock.agent.actions import to_proposal

    row = db.execute("SELECT * FROM proposals WHERE id = ?", (proposal["id"],)).fetchone()
    cuts = list(THEN.finditer(message))
    if len(cuts) + 1 == done + len(questions):
        text = message[cuts[done - 1].end():].strip()
    else:  # no "and" and no "?" added
        parts = [q.strip() for q in questions if q.strip()]
        text = " ".join(q if q[-1] in ".?!" or i == len(parts) - 1 else q + "." for i, q in enumerate(parts))
    payload = {**json.loads(row["payload_json"]), "then": text}
    db.execute("UPDATE proposals SET payload_json = ? WHERE id = ?", (json.dumps(payload, default=str), proposal["id"]))
    return to_proposal(db.execute("SELECT * FROM proposals WHERE id = ?", (proposal["id"],)).fetchone())


def _same(a: dict, b: dict) -> bool:  # `or None`: `columns_retyped` is there only when a type changes
    return all((a.get(k) or None) == (b.get(k) or None)
               for k in ("cells_changed", "rows_affected", "quarantined", "columns_added", "columns_retyped"))


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
    kept = kept_file(env.settings, dataset["user_id"], dataset["id"], row["id"])
    k = payload.get("kept")
    try:
        if k and version == row["base_version"] and kept.exists():  # nothing moved: the card's dry run is the result
            dr = DryRun(out=kept, impact=payload["impact"], before_after=payload.get("before_after") or [],
                        report=verifiers.Report(quarantined=k["quarantined"]), columns_changed=k["columns_changed"],
                        warnings=payload.get("warnings") or [])
            report_json = k["verifiers"]  # the dry run's report as it was, warned checks included
        else:
            kept.unlink(missing_ok=True)
            dr = dry_run(env, dataset, version, payload["code"], rows, payload.get("new_columns") or [])
            report_json = dr.report.as_json()
    except StepFailed as exc:  # the card shows `error`: the user's sentence; the model's text stays in `why`
        db.execute("UPDATE proposals SET status = 'failed', resolved_at = ?, payload_json = ? WHERE id = ?",
                   (now_iso(), json.dumps({**payload, "error": exc.user, "why": str(exc)}, default=str), row["id"]))
        raise ApiError(409, "conflict", f"Couldn't run it on version {version}. {exc.user} Nothing changed.") from None
    try:
        if version != row["base_version"] and not _same(dr.impact, payload["impact"]):
            fresh = {**_payload(payload["code"], payload["columns"], payload.get("new_columns") or [], rows, dr,
                                 payload.get("reading") or ""), "asked": payload.get("asked"), "rechecked_on": version,
                     **({"then": payload["then"]} if payload.get("then") else {})}
            db.execute("UPDATE proposals SET base_version = ?, payload_json = ?, status = 'pending' WHERE id = ?",
                       (version, json.dumps(fresh, default=str), row["id"]))
            dr.out.replace(kept)  # the new card's dry run, for the next OK
            return {"refreshed": to_proposal(db.execute("SELECT * FROM proposals WHERE id = ?", (row["id"],)).fetchone())}
        kind = "computed_column" if payload.get("new_columns") else "clean"
        reading = (payload.get("reading") or "").strip().rstrip(".")
        spec = StepSpec(kind=kind, summary=summary(dr.impact, dr.columns_changed, rows), created_by="chat",
                        notebook_code=notebook_code(payload["code"], rows), code=full_code(payload["code"], rows),
                        column_targets=list(dict.fromkeys(list(payload["columns"]) + dr.impact["columns_added"])),
                        gate="user", parse_failures=dr.report.quarantined, verifiers=report_json,
                        # Read as "**What does it do?** Upper-case every value in sex. You pressed OK in chat"
                        decisions=[{"question": "What does it do?", "chosen": reading or "It runs the code shown in chat",
                                    "alternatives": [], "reason": "You pressed OK in chat", "asked": payload.get("asked") or ""}])
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
