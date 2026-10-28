"""`ask_code`: questions a single SQL query can't answer well (docs/plans/chat-commands.md §1.1): a regression,
clustering, a custom statistic, fuzzy matching, a calculation in several dependent steps.

`medium` writes read-only pandas code (schema `AnalysisDraft`). The sandbox runs it on the current version in its
analysis mode, which may also import scipy and scikit-learn and writes the answer instead of a version. A failure
goes back to the model once (the client's repair). The answer is read back through DuckDB into the same `Result`
the SQL answerers return, so chips, tables, charts and "How do you know?" (the code) work unchanged. Nothing is
saved and no OK is asked: the CSV never changes. A question about something no column records stays an honest
"can't".
"""

import uuid

from sherlock.agent import prompts
from sherlock.agent.answerers import CantAnswer, Result, Toolkit, reading_text
from sherlock.llm.client import StructuredOutputError, fence
from sherlock.llm.schemas import AnalysisDraft
from sherlock.llm.wording import wording_problem
from sherlock.query.execute import SqlError, run_query
from sherlock.sandbox import runner as sandbox
from sherlock.sandbox.static_check import ANALYSIS_MODULES, check as static_check
from sherlock.storage import sql_path

import duckdb


def _scoped(code: str, selection: str | None, kit: Toolkit) -> str:
    """The code limited to the selection's rows, when the chat is scoped to one."""
    if not selection:
        return code
    from sherlock.query import context as qx

    with qx.connection(kit.env, kit.dataset, kit.dataset["current_version"]) as conn:
        ids = [r[0] for r in conn.execute(f"SELECT _row_id FROM t WHERE {selection}").fetchall()]  # noqa: S608
    return f"df = df[df[\"_row_id\"].isin({ids!r})]\n{code}"


def ask_code(kit: Toolkit, question: str, rid: str) -> Result:
    from sherlock.agent.commands import plain, version_path

    src = version_path(kit.env, kit.dataset, kit.dataset["current_version"])
    got: dict = {}

    def check(d: AnalysisDraft) -> None:
        if not d.answerable:
            return
        d.code = plain(d.code)
        problems = static_check(d.code, ANALYSIS_MODULES)
        if problems:
            raise ValueError("the sandbox refuses this code: " + "; ".join(str(p) for p in problems[:3]))
        out = src.parent / f".answer_{uuid.uuid4().hex}.parquet"
        try:
            r = sandbox.execute(kit.env.settings, _scoped(d.code, kit.rows.selection, kit), src, out, db=kit.env.db,
                                dataset_id=kit.dataset["id"], analysis=True)
            if not r.ok:
                raise ValueError(f"When the code ran on the file it failed: {r.error or 'unknown error'}. Fix the code.")
            conn = duckdb.connect(":memory:")
            try:
                got["out"] = run_query(conn, f"SELECT * FROM read_parquet({sql_path(out)})")
            except SqlError as exc:
                raise ValueError(f"Its answer couldn't be read back: {exc}. Leave a plain table in result.") from None
            finally:
                conn.close()
            got["truncated"] = r.truncated
        finally:
            out.unlink(missing_ok=True)
        if not got["out"]["rows"]:
            raise ValueError("The code ran but its answer is empty. If no rows match, say so with a one-row table.")

    messages = [{"role": "system", "content": prompts.SYSTEM},
                {"role": "user", "content": prompts.ANALYSIS.format(
                    context=kit.context, dtypes=fence("\n".join(f"- {c}: {t}" for c, t in kit.types.items())),
                    message=fence(question))}]
    try:
        draft = kit.llm.structured("medium", messages, AnalysisDraft, purpose="analysis", scope=kit.scope,
                                   validate=check).value
    except StructuredOutputError as exc:
        why = str(exc).split(": ", 1)[-1].removesuffix(". Fix the code.")
        raise CantAnswer(f"I couldn't work that out in code: {why[:300]}") from None
    if not draft.answerable:
        said = draft.reading.strip()
        raise CantAnswer("This file has no column that answers that" + (f": {said}" if said and not wording_problem(said) else "."))
    out = got["out"]
    res = Result(rid, draft.code, "", out["columns"], out["rows"], out["row_count"],
                 truncated=out["truncated"] or got.get("truncated", False), label="Worked out in code")
    res.extra.update({"reading": reading_text(draft.reading), "code": draft.code})
    return res
