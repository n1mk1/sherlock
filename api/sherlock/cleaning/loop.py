"""The headless Cleaner (TRD §7.2): the `clean` job.

For each issue, most severe first, while the budget lasts (`CLEAN_MAX_STEPS` issues attempted,
`CLEAN_MAX_SECONDS`, the job's token budget):
  diagnose (large) → candidates (large) → each candidate in the sandbox on a stratified sample,
  scored by the verifiers → the best on the full data, verified again → critic (medium) →
  gate → commit_step (commit or flag) or skip; then re-profile and pick the next issue.

Leakage and ID-like columns are never changed: they are logged as skipped without a model call.
Hand-edited cells keep their values unless the request includes them. A scope (a selection or the
rows added since the last clean) limits which rows a step may change. The run's state (`ended_by`,
time spent waiting for the model, skipped issues) is checkpointed in `jobs.state_json`, and the
report (`GET /report`) is assembled from it, the run's steps and the `issues` table.
"""

import json
import random
import shutil
import sqlite3
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import pandas as pd

from sherlock.cleaning import gate, prompts, verifiers
from sherlock.cleaning.helpers import __all__ as HELPER_NAMES
from sherlock.config import Settings
from sherlock.errors import ApiError
from sherlock.jobs.runner import JobCancelled, JobContext
from sherlock.llm.client import BudgetExceeded, CallScope, LLMClient, LLMUnavailable, StructuredOutputError, cap_values
from sherlock.llm.schemas import Candidates, Critique, Diagnosis
from sherlock.profile import service as profile_service
from sherlock.sandbox import runner as sandbox
from sherlock.sandbox.worker import output_select
from sherlock.steps.commit import Context, StepSpec, commit_step
from sherlock.storage import dataset_dir, sql_path

SAMPLE_ROWS = 2000
NEVER_CHANGE = {"leakage": "Records the outcome, so it is marked as leakage and not changed",
                "id_candidates": "Looks like an ID column, so it is left as is"}
SKIP_TEXT = {"leakage": "excluded from models", "id_candidates": "left as is"}
VOTE_DETECTORS = ("ambiguous_dates",)
VOTES = 3


@dataclass
class RunState:
    from_version: int
    max_steps: int
    max_seconds: int
    ended_by: str = "done"
    waited_for_model_s: float = 0.0
    attempted: int = 0
    started: float = field(default_factory=time.monotonic)
    handled: list[str] = field(default_factory=list)          # "detector|column" keys already attempted
    skipped: list[dict] = field(default_factory=list)          # {issue_id, column, detector, reason}
    hand_edited_skipped: list[dict] = field(default_factory=list)
    step_ids: list[str] = field(default_factory=list)

    def json(self) -> dict:
        return {
            "from_version": self.from_version, "ended_by": self.ended_by,
            "max_steps": self.max_steps, "max_seconds": self.max_seconds,
            "waited_for_model_s": round(self.waited_for_model_s, 1), "attempted": self.attempted,
            "handled": self.handled, "skipped": self.skipped,
            "hand_edited_skipped": self.hand_edited_skipped[:500], "step_ids": self.step_ids,
        }


def key(issue: dict) -> str:
    return f"{issue['detector']}|{issue['column']}"


def issue_line(issue: dict) -> str:
    what = issue["detector"].replace("_", " ")
    where = f" in {issue['column']}" if issue["column"] else ""
    return f"{issue['count']:,} rows with {what}{where}: {issue.get('proposal') or ''}".strip()


ISSUE_WORDS = {
    "missing": "missing values", "mixed_types": "values of another type", "sentinels": "placeholder values",
    "whitespace_case": "spacing or case variants", "near_duplicate_categories": "near-duplicate categories",
    "duplicates": "duplicate rows", "impossible_values": "impossible values", "numbers_as_text": "numbers stored as text",
    "ambiguous_dates": "ambiguous dates", "mojibake": "garbled characters", "unit_mixes": "mixed units",
    "cross_column": "values out of order", "functional_dependency": "rows breaking a dependency", "outliers": "outliers",
}


def short_line(issue: dict) -> str:
    """The log's one-line name for an issue: "263 missing values"."""
    return f"{issue['count']:,} {ISSUE_WORDS.get(issue['detector'], issue['detector'].replace('_', ' '))}"


def _json(value, limit: int = 1500) -> str:
    text = json.dumps(value, default=str, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 1] + "…"


class Cleaner:
    def __init__(self, ctx: JobContext, llm: LLMClient) -> None:
        self.ctx = ctx
        self.llm = llm
        self.settings: Settings = ctx.settings
        self.db: sqlite3.Connection = ctx.db
        self.params = ctx.params
        self.dataset = self._dataset()
        self.folder = dataset_dir(self.settings, self.dataset["user_id"], self.dataset["id"])
        self.state = RunState(from_version=self.dataset["current_version"], max_steps=self.settings.clean_max_steps,
                              max_seconds=self.settings.clean_max_seconds)
        self.scope = CallScope(user_id=self.dataset["user_id"], dataset_id=self.dataset["id"], job_id=ctx.id,
                               on_wait=lambda text: ctx.log(text, level="warn", icon="wait"))
        self.work = self.settings.data_dir / ".clean" / ctx.id
        self.work.mkdir(parents=True, exist_ok=True)

    # --- data access ----------------------------------------------------------------------------

    def _dataset(self) -> sqlite3.Row:
        return self.db.execute("SELECT * FROM datasets WHERE id = ?", (self.ctx.dataset_id,)).fetchone()

    def _current_parquet(self) -> tuple[int, Path]:
        d = self._dataset()
        v = self.db.execute("SELECT parquet_path FROM versions WHERE dataset_id = ? AND version = ?",
                            (d["id"], d["current_version"])).fetchone()
        return d["current_version"], self.folder / v["parquet_path"]

    def _card(self) -> dict:
        return profile_service.get_or_build(self.settings, self.db, self.ctx.cache, self._dataset())

    def _read(self, path: Path) -> pd.DataFrame:
        conn = duckdb.connect(":memory:")
        try:
            return conn.execute(f"SELECT * FROM read_parquet({sql_path(path)}) ORDER BY _row_id").df()
        finally:
            conn.close()

    def _checkpoint(self) -> None:
        self.db.execute("UPDATE jobs SET state_json = ? WHERE id = ?", (json.dumps(self.state.json()), self.ctx.id))

    # --- scope and protected cells --------------------------------------------------------------

    def scope_row_ids(self) -> list[int] | None:
        scope = self.params.get("scope") or {"kind": "all"}
        if scope.get("kind") == "selection":
            sel = self.db.execute("SELECT * FROM selections WHERE id = ? AND dataset_id = ?",
                                  (scope.get("selection_id"), self.dataset["id"])).fetchone()
            if sel is None:
                raise ValueError("The selection to clean no longer exists.")
            if sel["row_ids_json"]:
                return json.loads(sel["row_ids_json"])
            _, path = self._current_parquet()
            conn = duckdb.connect(":memory:")
            try:
                conn.execute(f"CREATE VIEW t AS SELECT * FROM read_parquet({sql_path(path)})")
                return [r[0] for r in conn.execute(f"SELECT _row_id FROM t WHERE {sel['predicate']}").fetchall()]
            finally:
                conn.close()
        if scope.get("kind") == "new_rows":
            if scope.get("row_ids"):
                return [int(i) for i in scope["row_ids"]]
            return self._rows_added_since_last_clean()
        return None

    def _rows_added_since_last_clean(self) -> list[int]:
        chain = json.loads(self.db.execute(
            "SELECT effective_step_ids_json FROM versions WHERE dataset_id = ? AND version = ?",
            (self.dataset["id"], self.dataset["current_version"])).fetchone()[0])
        steps = {r["id"]: r for r in self.db.execute(
            f"SELECT id, created_by FROM steps WHERE id IN ({','.join('?' for _ in chain)})", chain)} if chain else {}
        last_clean = max((i for i, s in enumerate(chain) if steps[s]["created_by"] == "cleaner"), default=-1)
        later = chain[last_clean + 1:]
        if not later:
            return []
        rows = self.db.execute(
            f"SELECT row_id FROM lineage WHERE dataset_id = ? AND column = '_row' AND new_value = 'added' "
            f"AND step_id IN ({','.join('?' for _ in later)})", (self.dataset["id"], *later)).fetchall()
        return [r[0] for r in rows]

    def protected_cells(self) -> set[tuple[int, str]]:
        if self.params.get("include_user_edited"):
            return set()
        return {(r[0], r[1]) for r in self.db.execute(
            "SELECT row_id, column FROM user_edited_cells WHERE dataset_id = ?", (self.dataset["id"],))}

    # --- the run --------------------------------------------------------------------------------

    def run(self) -> dict:
        s = self.settings
        allowed = self.scope_row_ids()
        if allowed is not None and not allowed:
            self.ctx.log("There are no rows in scope, so there's nothing to clean.", icon="info")
            self.state.ended_by = "done"
            return self._finish()
        self.allowed = set(allowed) if allowed is not None else None
        self.protected = self.protected_cells()
        self._checkpoint()  # the report (and the live screen's counts) can read the run from the start
        self._log_typing_step()
        try:
            while True:
                self.ctx.check_cancel()
                if self.state.attempted >= s.clean_max_steps:
                    self.state.ended_by = "steps"
                    break
                if time.monotonic() - self.state.started >= s.clean_max_seconds:
                    self.state.ended_by = "time"
                    break
                issue = self._next_issue()
                if issue is None:
                    break
                self._handle(issue)
                self._checkpoint()
        except JobCancelled:
            self.state.ended_by = "stopped"
            self._checkpoint()
            raise
        except BudgetExceeded:
            self.state.ended_by = "tokens"
        except LLMUnavailable as exc:
            self.state.ended_by = "error"
            self.ctx.log(exc.message, level="error", icon="error")
            if not self.state.step_ids:
                self._checkpoint()
                raise
        return self._finish()

    def _finish(self) -> dict:
        self._checkpoint()
        shutil.rmtree(self.work, ignore_errors=True)
        d = self._dataset()
        return {"from_version": self.state.from_version, "to_version": d["current_version"],
                "ended_by": self.state.ended_by, "steps": len(self.state.step_ids)}

    def _log_typing_step(self) -> None:
        """The automatic typing step opens the log (it ran during profiling)."""
        row = self.db.execute(
            "SELECT * FROM steps WHERE dataset_id = ? AND created_by = 'system' AND kind = 'clean' ORDER BY no LIMIT 1",
            (self.dataset["id"],)).fetchone()
        if row is not None and (self.params.get("scope") or {}).get("kind", "all") == "all":
            self.ctx.log(f"{row['summary']} (automatic step {row['no']})", icon="check", column="all columns",
                         gate="commit", step_id=row["id"], step_no=row["no"])

    def _next_issue(self) -> dict | None:
        card = self._card()
        # Columns that record the outcome or identify rows are marked, never changed, whatever the issue.
        leaking = {c["column"] for c in card.get("leakage_candidates", [])}
        ids = set(card.get("id_columns", []))
        for issue in sorted(card["issues"], key=lambda i: -i["severity"]):
            if key(issue) in self.state.handled:
                continue
            reason = NEVER_CHANGE.get(issue["detector"])
            kind = issue["detector"]
            if reason is None and issue["column"] in leaking:
                reason, kind = f"{issue['column']} records the outcome, so it is not changed", "leakage"
            elif reason is None and issue["column"] in ids:
                reason, kind = f"{issue['column']} looks like an ID column, so it is left as is", "id_candidates"
            if reason is not None:
                self.state.handled.append(key(issue))
                self._skip(issue, reason, log_text=SKIP_TEXT[kind])
                continue
            return issue
        return None

    def _skip(self, issue: dict, reason: str, candidates=None, log_text: str | None = None, checks=None) -> None:
        self.state.skipped.append({"issue_id": issue["id"], "column": issue["column"], "detector": issue["detector"],
                                   "reason": reason})
        self.db.execute("UPDATE issues SET outcome = 'skipped', skip_reason = ? WHERE id = ?", (reason, issue["id"]))
        self.ctx.log(reason, icon="skip", column=issue["column"], gate="skip", candidates=candidates,
                     detail=log_text or "skipped", issue_id=issue["id"], checks=checks)

    # --- one issue ------------------------------------------------------------------------------

    def _handle(self, issue: dict) -> None:
        self.state.handled.append(key(issue))
        self.state.attempted += 1
        column = issue["column"]
        cap = min(self.settings.clean_max_steps, self.state.attempted + 5)
        self.ctx.progress(self.state.attempted, cap, f"Step {self.state.attempted} · {column or 'rows'}")
        self.ctx.log(short_line(issue), icon="running", column=column, detail="checking candidates", issue_id=issue["id"])
        version, path = self._current_parquet()
        before = self._read(path)
        card = self._card()
        try:
            diagnosis = self._diagnose(issue, card, before)
        except StructuredOutputError:
            return self._skip(issue, "model output invalid")
        if diagnosis.leave_as_is:
            return self._skip(issue, f"Left as is: {diagnosis.cause}")
        try:
            proposed = self._propose(issue, diagnosis, before)
        except StructuredOutputError:
            return self._skip(issue, "model output invalid")
        sample_path = self.work / f"sample_{uuid.uuid4().hex}.parquet"
        _copy_rows(path, sample_path, self._sample_ids(before, issue))
        sample = self._read(sample_path)
        scored = []
        for cand in proposed.candidates:
            self.ctx.check_cancel()
            out = self.work / f"cand_{uuid.uuid4().hex}.parquet"
            r = sandbox.execute(self.settings, cand.code, sample_path, out, db=self.db,
                                dataset_id=self.dataset["id"], job_id=self.ctx.id,
                                should_stop=self._stop_requested)
            if r.cancelled:
                raise JobCancelled()
            if not r.ok:
                scored.append((cand, 0.0, None, r.error or "the code failed"))
                continue
            try:
                after = self._restrict(sample, self._read(out))
            except ScopeError as exc:
                scored.append((cand, 0.0, None, str(exc)))
                continue
            report = verifiers.verify(sample, after, issue["detector"], column)
            scored.append((cand, report.score, report, None if report.passed else _first_failure(report)))
        chips = [{"label": c.label, "chosen": False} for c, *_ in scored]
        best_i = max(range(len(scored)), key=lambda i: scored[i][1]) if scored else None
        if best_i is None or scored[best_i][1] == 0.0:
            why = next((e for *_, e in scored if e), "no candidate passed the checks")
            return self._skip(issue, f"No candidate passed the checks ({why})", candidates=chips)
        best, best_score, sample_report, _ = scored[best_i]
        chips[best_i]["chosen"] = True

        # The best candidate on the full data, verified again; the gate uses the real blast.
        self.ctx.check_cancel()
        full_out = self.work / f"full_{uuid.uuid4().hex}.parquet"
        r = sandbox.execute(self.settings, best.code, path, full_out, db=self.db,
                            dataset_id=self.dataset["id"], job_id=self.ctx.id,
                                should_stop=self._stop_requested)
        if r.cancelled:
            raise JobCancelled()
        if not r.ok:
            return self._skip(issue, f"Failed on the full data ({r.error})", candidates=chips)
        try:
            after_full = self._restrict(before, self._read(full_out))
        except ScopeError as exc:
            return self._skip(issue, f"Not applied: {exc}", candidates=chips)
        full_report = verifiers.verify(before, after_full, issue["detector"], column)
        if not full_report.passed:
            return self._skip(issue, f"Failed checks on the full data ({_first_failure(full_report)})", candidates=chips,
                              checks=full_report.hard)
        if full_report.cells_changed == 0 and full_report.quarantined == 0:
            return self._skip(issue, "The fix changed nothing", candidates=chips)
        try:
            critique = self._critic(issue, best, before, after_full, full_report)
            critic_clean = not critique.changed_something_it_shouldnt and not critique.concerns
        except StructuredOutputError:
            critique, critic_clean = None, False
        user_cols = [c for c in before.columns if c not in verifiers.SYSTEM]
        decision = gate.decide([s for _, s, *_ in scored], critic_clean,
                               full_report.cells_changed + full_report.quarantined, len(before) * max(len(user_cols), 1))
        if decision.gate == "skip":
            return self._skip(issue, f"Skipped: {decision.reason}", candidates=chips, checks=full_report.hard)
        restricted = full_out
        if self.allowed is not None or self.protected:
            restricted = self.work / f"commit_{uuid.uuid4().hex}.parquet"
            _write(after_full, restricted, _types(path))
        flag_reason = decision.reason if decision.gate == "flag" else None
        if critique and critique.concerns and decision.gate == "flag":
            flag_reason = f"{decision.reason}; the review noted: {critique.concerns[0]}"
        spec = StepSpec(
            kind="clean", summary=f"{best.label} ({column})" if column else best.label, created_by="cleaner",
            notebook_code=best.code.rstrip() + "\ndf = result\n", code=best.code, column_targets=[column] if column else [],
            helpers_used=[h for h in HELPER_NAMES if h + "(" in best.code], confidence=decision.confidence,
            gate=decision.gate, flag_reason=flag_reason, parse_failures=full_report.quarantined,
            decisions=[{"question": f"How to fix {issue['detector'].replace('_', ' ')} in {column or 'the rows'}?",
                        "chosen": best.label, "alternatives": [c.label for c, *_ in scored if c is not best],
                        "reason": diagnosis.cause}],
            verifiers=full_report.as_json(), job_id=self.ctx.id,
        )
        try:
            step, _ = commit_step(Context(self.settings, self.db, self.ctx.cache, self.ctx.bus), self.dataset["id"],
                                  version, spec, lambda _old, out: shutil.copyfile(restricted, out))
        except ApiError as exc:
            if exc.status == 409:
                return self._skip(issue, "The data changed while this step ran", candidates=chips)
            raise
        self.state.step_ids.append(step["id"])
        outcome = "fixed" if decision.gate == "commit" else "flagged"
        self.db.execute("UPDATE issues SET outcome = ?, handled_by_step_id = ? WHERE id = ?",
                        (outcome, step["id"], issue["id"]))
        text = (f"committed · step {step['no']}" if decision.gate == "commit"
                else f"committed with a flag · step {step['no']} · confidence {decision.confidence:.2f}")
        self.ctx.log(best.expected_effect, icon="check" if decision.gate == "commit" else "flag", column=column,
                     gate=decision.gate, candidates=chips, step_id=step["id"], step_no=step["no"],
                     confidence=decision.confidence, detail=text, checks=full_report.hard, issue_id=issue["id"])

    def _stop_requested(self) -> bool:
        """Polled while a sandbox worker runs, so Stop kills it instead of waiting for it."""
        try:
            self.ctx.check_cancel()
            return False
        except JobCancelled:
            return True

    # --- model calls ----------------------------------------------------------------------------

    def _messages(self, user: str) -> list[dict]:
        return [{"role": "system", "content": prompts.SYSTEM}, {"role": "user", "content": user}]

    def _column_context(self, issue: dict, card: dict, df: pd.DataFrame) -> dict:
        column = issue["column"]
        entry = next((c for c in card["columns"] if c["name"] == column), None)
        if entry:
            entry = {k: entry[k] for k in ("name", "type", "role", "missing", "distinct", "stats", "top_values", "unit") if k in entry}
        samples = cap_values(df[column].dropna().astype(str).drop_duplicates().head(20)) if column in df else []
        decisions = [json.loads(r[0]) for r in self.db.execute(
            "SELECT decisions_json FROM steps WHERE dataset_id = ? AND created_by = 'cleaner' ORDER BY no DESC LIMIT 10",
            (self.dataset["id"],))]
        return {"entry": entry, "samples": samples, "decisions": [d for ds in decisions for d in ds][:10]}

    def _track(self, completion) -> None:
        self.state.waited_for_model_s += completion.waited_s

    def _diagnose(self, issue: dict, card: dict, df: pd.DataFrame) -> Diagnosis:
        cc = self._column_context(issue, card, df)
        columns = ", ".join(f"{c['name']} ({c['type']})" for c in card["columns"])
        user = prompts.DIAGNOSE.format(
            issue_line=issue_line(issue), detector=issue["detector"], column=issue["column"] or "(rows)",
            rows=card["row_count"], columns=columns, column_card=_json(cc["entry"]), samples=_json(cc["samples"]),
            examples=_json(cap_values(issue["examples"], 10)), details=_json(issue.get("details") or {}, 600),
            decisions=_json(cc["decisions"], 1200) if cc["decisions"] else "none yet",
        )
        if issue["detector"] in VOTE_DETECTORS:
            votes = []
            for _ in range(VOTES):
                out = self.llm.structured("large", self._messages(user), Diagnosis, purpose="diagnose",
                                          scope=self.scope, temperature=0.7)
                self._track(out.completion)
                votes.append(out.value)
            counts = Counter(v.preferred_option for v in votes)
            option, n = counts.most_common(1)[0]
            chosen = next(v for v in votes if v.preferred_option == option)
            if n < 2:  # no majority: the conservative option (the first, by the prompt's ordering)
                chosen = chosen.model_copy(update={"preferred_option": 0})
            return chosen
        out = self.llm.structured("large", self._messages(user), Diagnosis, purpose="diagnose", scope=self.scope)
        self._track(out.completion)
        return out.value

    def _propose(self, issue: dict, diagnosis: Diagnosis, df: pd.DataFrame) -> Candidates:
        column = issue["column"]
        approaches = list(diagnosis.approach_options)
        if 0 <= diagnosis.preferred_option < len(approaches):
            approaches.insert(0, approaches.pop(diagnosis.preferred_option))
        samples = cap_values(df[column].dropna().astype(str).drop_duplicates().head(20)) if column in df else []
        user = prompts.PROPOSE.format(
            issue_line=issue_line(issue), column=column or "(rows)", cause=diagnosis.cause,
            approaches="; ".join(approaches), dtypes=_json({c: str(t) for c, t in df.dtypes.items()}, 2000),
            samples=_json(samples), examples=_json(cap_values(issue["examples"], 10)), helpers=prompts.HELPERS,
        )
        out = self.llm.structured("large", self._messages(user), Candidates, purpose="propose", scope=self.scope,
                                  max_tokens=6000)
        self._track(out.completion)
        return out.value

    def _critic(self, issue, best, before: pd.DataFrame, after: pd.DataFrame, report) -> Critique:
        column = issue["column"]
        changes = []
        if column in before and column in after:
            b, a = before.set_index("_row_id")[column], after.set_index("_row_id")[column]
            diff = b.astype(str) != a.astype(str)
            for rid in list(b.index[diff])[:12]:
                changes.append(f"{b[rid]!r} → {a[rid]!r}")
        effect = (f"{report.cells_changed} cells changed, {report.unrelated_changed} outside {column}, "
                  f"{report.quarantined} rows quarantined; the issue went from {report.issue_before} to {report.issue_after}")
        user = prompts.CRITIC.format(issue_line=issue_line(issue), column=column or "(rows)", label=best.label,
                                     code=best.code, effect=effect, changes=_json(changes), checks=_json(report.hard))
        out = self.llm.structured("medium", self._messages(user), Critique, purpose="critic", scope=self.scope)
        self._track(out.completion)
        return out.value

    # --- sampling and restriction ---------------------------------------------------------------

    def _sample_ids(self, df: pd.DataFrame, issue: dict) -> list[int] | None:
        """At most 2,000 rows, stratified by issue presence: up to half are rows with the issue.
        None means every row."""
        if len(df) <= SAMPLE_ROWS:
            return None
        column = issue["column"]
        examples = issue.get("examples") or []
        if column is None:
            present = df["_row_id"].isin([e for e in examples if isinstance(e, int)])
        elif issue["detector"] == "missing":
            present = df[column].isna()
        else:
            present = df[column].astype(str).isin({str(e) for e in examples})
        rng = random.Random(42)
        with_issue = df.index[present].tolist()
        rest = df.index[~present].tolist()
        take = rng.sample(with_issue, min(len(with_issue), SAMPLE_ROWS // 2))
        take += rng.sample(rest, min(len(rest), SAMPLE_ROWS - len(take)))
        return sorted(int(i) for i in df.loc[take, "_row_id"])

    def _restrict(self, before: pd.DataFrame, after: pd.DataFrame) -> pd.DataFrame:
        """Keep changes only to rows in scope and to cells nobody edited by hand."""
        if self.allowed is None and not self.protected:
            return after
        out = after.set_index("_row_id")
        b = before.set_index("_row_id")
        out_of_scope = [i for i in b.index if self.allowed is not None and i not in self.allowed]
        cols = [c for c in b.columns if c in out.columns]
        for c in cols:
            if not out_of_scope:
                break
            if out[c].dtype != b[c].dtype and not b.loc[out_of_scope, c].equals(out.loc[out_of_scope, c]):
                raise ScopeError(f"it changes the type of {c}, which can't be done for only some rows")
            out.loc[out_of_scope, c] = b.loc[out_of_scope, c]
        kept = []
        for rid, col in self.protected:
            if rid in out.index and col in out.columns and str(out.at[rid, col]) != str(b.at[rid, col]):
                if out[col].dtype != b[col].dtype:
                    continue  # a retyped column can't keep the text; the hand edit's value is parsed with it
                out.at[rid, col] = b.at[rid, col]
                kept.append({"row_id": int(rid), "column": col})
        for k in kept:
            if k not in self.state.hand_edited_skipped:
                self.state.hand_edited_skipped.append(k)
        return out.reset_index()


class ScopeError(Exception):
    """A candidate that can't be limited to the rows in scope."""


def _types(path: Path) -> dict[str, str]:
    conn = duckdb.connect(":memory:")
    try:
        return {r[0]: str(r[1]) for r in conn.execute(f"DESCRIBE SELECT * FROM read_parquet({sql_path(path)})").fetchall()}
    finally:
        conn.close()


def _write(df: pd.DataFrame, path: Path, input_types: dict[str, str]) -> None:
    """Write a frame back to Parquet, casting columns to their input types where pandas changed them
    only in transit (the sandbox worker's rule)."""
    conn = duckdb.connect(":memory:")
    try:
        conn.register("result_frame", df)
        conn.execute(f"COPY ({output_select(df, input_types)}) TO {sql_path(path)} (FORMAT PARQUET)")
    finally:
        conn.close()


def _copy_rows(src: Path, dst: Path, row_ids: list[int] | None) -> None:
    conn = duckdb.connect(":memory:")
    try:
        where = "" if row_ids is None else f" WHERE list_contains([{', '.join(str(int(i)) for i in row_ids)}], _row_id)"
        conn.execute(f"COPY (SELECT * FROM read_parquet({sql_path(src)}){where} ORDER BY _row_id) TO {sql_path(dst)} "
                     "(FORMAT PARQUET)")
    finally:
        conn.close()


def _first_failure(report: verifiers.Report) -> str:
    for name, value in report.hard.items():
        if value != "pass":
            return f"{name}: {value.removeprefix('fail: ')}"
    return "checks failed"

