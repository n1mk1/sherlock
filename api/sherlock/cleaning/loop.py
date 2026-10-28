"""The headless Cleaner (TRD §7.2): the `clean` job.

For each issue, most severe first, while the budget lasts (`CLEAN_MAX_STEPS` issues attempted,
`CLEAN_MAX_SECONDS`, the job's token budget):
  diagnose (large) → candidates (large) → each candidate in the sandbox on a stratified sample,
  scored by the verifiers → the best on the full data, verified again → critic (medium) →
  gate → commit_step (commit or flag) or skip; then re-profile and pick the next issue.

Leakage and ID-like columns are never changed: they are logged as skipped without a model call
(an ID column's placeholders and formatted numbers are still fixed, `spec.type_fix`). A value
that breaks the column's domain rule (`spec.domain_rule`) is quarantined by the rule's own fix.
What the run knows about a detector comes from its spec (`registry`, PRD CLEAN-12).
A run started from a cleaning plan (`params.plan`, PRD CLEAN-8a) skips the fixes the plan leaves
unticked the same way, "not in your plan"; issues the plan doesn't list (found mid-run) are attempted,
unless they are deeper than the plan's depth (PRD CLEAN-15): those are skipped as "deeper than your scan".
The user's own steps (CLEAN-8b) run first, then the issues; a step the user asked for, or a fix they
rewrote, carries their instruction into the prompts, isn't ended by the diagnosis' "leave as is", and
at low confidence commits with a flag instead of being skipped. Hard checks still skip it.
Hand-edited cells keep their values unless the request includes them. A scope (a selection or the
rows added since the last clean) limits which rows a step may change. The run's state (`ended_by`,
time spent waiting for the model, skipped issues) is checkpointed in `jobs.state_json`, and the
report (`GET /report`) is assembled from it, the run's steps and the `issues` table.
"""

import ast
import json
import random
import re
import shutil
import sqlite3
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import pandas as pd

from sherlock.agent.web import notes_for
from sherlock.cleaning import gate, levels, prompts, registry, verifiers
from sherlock.cleaning.plan import (
    DATE_ORDERS, DEPTH, USER_DETECTOR, both_ways, key, needs_order, never_change, order_instruction, run_params,
)
from sherlock.cleaning.helpers import __all__ as HELPER_NAMES
from sherlock.cleaning.helpers import keep_outside_scope
from sherlock.cleaning.rules import store as rule_store
from sherlock.config import Settings
from sherlock.errors import ApiError
from sherlock.jobs.runner import JobCancelled, JobContext
from sherlock.llm.client import BudgetExceeded, CallScope, LLMClient, LLMUnavailable, StructuredOutputError, cap_values, escape_data
from sherlock.llm.schemas import Candidate, Candidates, Critique, Diagnosis
from sherlock.profile import service as profile_service
from sherlock.sandbox import runner as sandbox
from sherlock.sandbox.worker import output_select
from sherlock.steps.commit import Context, StepSpec, commit_step
from sherlock.llm.wording import number_in_words
from sherlock.storage import dataset_dir, sql_path

SAMPLE_ROWS = 2000
# Where a column's meaning comes from, best first: a dictionary the user linked, one Sherlock found, the web
# (docs/plans/tavily.md §3.4).
MEANING_KINDS = ("dictionary", "found", "web")
MEANING_CHARS = 300  # a note's sentence, at most, in a prompt
EVIDENCE_KEYS = ("url", "title", "excerpt", "retrieved_at")
NOT_IN_PLAN = "You left this out of the plan"
TOO_DEEP = "Deeper than the cleaning depth you chose"
# Why an issue was skipped (Schema §2.8 `issues.skip_kind`), and the report line each lands on (PRD CLEAN-6).
SKIP_KINDS = {
    "kept_by_design": "kept_by_design",                                                # marked, not changed
    "left_as_is": "checked_and_kept",
    "failed_checks": "couldnt_fix", "disagreement": "couldnt_fix", "gate": "couldnt_fix",
    "model_error": "couldnt_fix", "conflict": "couldnt_fix",
    "unticked": "not_attempted", "needs_choice": "not_attempted", "budget": "not_attempted",
}
BUDGET_WORDS = {"steps": "issue", "time": "time", "tokens": "model"}
USER_SEVERITY = 2.0  # above any detector's (at most 1.0): the user's steps go first
USER_ISSUE_LINE = "A change the user asked for; the instruction is in the data block"
LEFT_AS_IS = "the values look legitimate"  # when the diagnosis' own cause has digits
VOTES = 3  # diagnoses of a `spec.vote` detector (ambiguous dates); the majority wins


@dataclass
class RunState:
    from_version: int
    max_steps: int
    max_seconds: int
    ended_by: str = "done"
    waited_for_model_s: float = 0.0
    attempted: int = 0
    planned: int = 0                                            # issues expected at the start: the progress total
    started: float = field(default_factory=time.monotonic)
    handled: list[str] = field(default_factory=list)          # "detector|column" keys already attempted
    skipped: list[dict] = field(default_factory=list)          # {issue_id, column, detector, reason}
    hand_edited_skipped: list[dict] = field(default_factory=list)
    step_ids: list[str] = field(default_factory=list)
    plan_id: str | None = None                                  # the cleaning plan this run started from
    plan_outcomes: dict[str, dict] = field(default_factory=dict)  # plan item id → {outcome, reason?, step_id?, step_no?}

    def json(self) -> dict:
        return {
            "from_version": self.from_version, "ended_by": self.ended_by, "plan_id": self.plan_id,
            "max_steps": self.max_steps, "max_seconds": self.max_seconds,
            "waited_for_model_s": round(self.waited_for_model_s, 1), "attempted": self.attempted,
            "handled": self.handled, "skipped": self.skipped,
            "hand_edited_skipped": self.hand_edited_skipped[:500], "step_ids": self.step_ids,
            "plan_outcomes": self.plan_outcomes,
        }


def run_key(issue: dict) -> str:
    """What `handled` records: the issue key, or the plan item for a step the user added."""
    return f"user|{issue['plan_item_id']}" if issue.get("user") else key(issue)


def issue_line(issue: dict) -> str:
    if issue.get("user"):  # the instruction is the user's text: it goes inside the data block
        return USER_ISSUE_LINE
    what = issue["detector"].replace("_", " ")
    where = f" in {issue['column']}" if issue["column"] else ""
    return f"{issue['count']:,} rows with {what}{where}: {issue.get('proposal') or ''}".strip()


def short_line(issue: dict) -> str:
    """The log's one-line name for an issue: "263 missing values", "Your step: trim spaces in name"."""
    if issue.get("user"):
        text = issue["instruction"]
        return f"Your step: {text if len(text) <= 80 else text[:79] + '…'}"
    return f"{issue['count']:,} {issue_words(issue)}"


def rule_candidate(issue: dict) -> Candidate | None:
    """The domain rule's own fix for an issue of a `spec.domain_rule` detector (a negative age, an age
    of 999): quarantine the rows it names, built by code, so a value outside the column's domain has a
    fix whatever the model proposes. The diagnosis' "leave as is" doesn't end such an issue, the fix
    joins the candidates and wins whenever it passes the checks (no guessed replacement), and a low
    confidence or the critic's objection to a fix that only quarantines what the rule names flags the
    step instead of skipping it (TRD §7.2). None for other issues, or a rule the details don't give."""
    spec = registry.get(issue["detector"])
    if issue.get("user") or not registry.setting(issue, "domain_rule") or spec.code_fix is None:
        return None
    return spec.code_fix(issue)


def code_fix(issue: dict) -> Candidate | None:
    """The code's own fix for another detector with a `spec.code_fix` (TRD §7.2, "Code fixes"): numbers
    stored as text are parsed with `parse_numbers` and the values it can't read are quarantined; a
    near-duplicate's pairs are merged; spacing and case variants take the most common spelling. It is
    tried when the model's proposal fails (a reply cut off at its token cap), none of its candidates
    passes the checks or the best of them only sets rows aside, and in place of a fix the critic vetoed;
    on a measure column the diagnosis' "leave as is" doesn't end it. None for others."""
    spec = registry.get(issue["detector"])
    if issue.get("user") or registry.setting(issue, "domain_rule") or spec.code_fix is None:
        return None
    return spec.code_fix(issue)


def order_candidate(issue: dict) -> Candidate | None:
    """The date order the user picked (PRD CLEAN-8b) as code's own parse: `parse_dates_smart` with that
    `order_hint`, the values it can't read quarantined. The user's choice settles what the data can't, so
    when it passes the checks it is the fix, and candidates that read the dates the other way are no
    disagreement (TRD §7.2). None without a picked order."""
    order, column = issue.get("date_order"), issue.get("column")
    if not order or column is None or issue.get("user"):
        return None
    code = (f"parsed = parse_dates_smart(df[{column!r}], order_hint={order!r})\nresult = df.copy()\n"
            f"result[{column!r}] = parsed\n"
            f"result = quarantine_rows(result, parse_failures(df[{column!r}], parsed), {'unparsed: ' + column!r})")
    return Candidate(label=f"Parse dates {DATE_ORDERS[order]}", code=code,
                     expected_effect="Reads every date in the order you picked; values that aren't dates are set aside.")


def measure_column(issue: dict, card: dict) -> bool:
    """The issue's column is a measure on the DataCard (numbers stored as text, say "$4.20")."""
    entry = next((c for c in card.get("columns", []) if c["name"] == issue.get("column")), None)
    return bool(entry and entry.get("role") == "measure")


def queue(issues: list[dict], card: dict, plan_levels: dict[str, str] | None = None) -> list[dict]:
    """The card's issues in the order the Cleaner attempts them (TRD §7.2): by level, breaks first (the
    plan's level for a key it lists, else the code's default level, PRD CLEAN-8c), then most severe
    first; an issue that is never changed has no level and comes first, since it is skipped at once.
    Then an issue whose spec `runs_before` other detectors moves up to just before the first of their
    issues on its column, never down: a column's placeholders go before its domain rule, so a "-999"
    age becomes a missing value rather than quarantining its row; the rule then takes what is left."""
    plan_levels = plan_levels or {}

    def level(i: dict) -> str | None:
        return plan_levels.get(key(i)) or levels.default_level(i, card)

    ordered = sorted(issues, key=lambda i: (levels.rank(level(i)), -i["severity"]))
    for i in [i for i in ordered if registry.get(i["detector"]).runs_before]:
        after = registry.get(i["detector"]).runs_before
        first = next((j for j in ordered if j["column"] == i["column"] and j["detector"] in after), None)
        if first is not None and ordered.index(first) < ordered.index(i):
            ordered.remove(i)
            ordered.insert(ordered.index(first), i)
    return ordered


def rule_only(report: verifiers.Report) -> bool:
    """A fix that only quarantines rows and leaves none of the issue: no cell rewritten."""
    return report.quarantined > 0 and report.cells_changed == 0 and report.issue_after == 0


def step_summary(label: str, column: str | None) -> str:
    """"<label> (<column>)", without naming the column twice: a label that already names it as a word
    ("... (units)", "... on units", "... unit price" for unit_price) is the title as it is."""
    if not column:
        return label
    names = {column, column.replace("_", " ")}
    if any(re.search(rf"(?<!\w){re.escape(n)}(?!\w)", label, re.I) for n in names):
        return label
    return f"{label} ({column})"


def runnable(code: str) -> str:
    """A candidate's code with its line breaks back when the model escaped them twice: a reply whose
    code reads `result = df.copy()\\nresult[...] = ...` on one line doesn't parse, and with its
    literal `\\n` read as line breaks it does. Code that parses, or still doesn't, is left as it came."""
    try:
        ast.parse(code)
        return code
    except SyntaxError:
        pass
    fixed = code.replace("\\n", "\n")
    try:
        ast.parse(fixed)
    except SyntaxError:
        return code
    return fixed


def order_needed(issue: dict) -> str:
    """The skip reason for dates that read both ways: no model call and no guess."""
    shown = "; ".join(f"{v} is {d} or {m}" for v, d, m in both_ways(issue.get("examples") or [])[:2])
    return ("Left as text: every date reads both ways" + (f" ({shown})" if shown else "")
            + ", so the order is yours to choose: pick it in the cleaning plan")


def issue_words(issue: dict) -> str | None:
    """What the issue's detector counts, for the log's "263 → 0 missing values"; None for a user's step."""
    if issue.get("user"):
        return None
    return registry.label(issue["detector"])


DIGIT = re.compile(r"\d")


def prose(text: str | None) -> str | None:
    """A model's sentence as the log, report and steps show it: only without digits or a number in
    words (CLAUDE.md Rule 2: a cleaning line's numbers come from the verifier report), else None."""
    text = (text or "").strip()
    return text if text and not DIGIT.search(text) and not number_in_words(text) else None


def _json(value, limit: int = 1500) -> str:
    text = json.dumps(value, default=str, ensure_ascii=False)
    return _safe(text if len(text) <= limit else text[: limit - 1] + "…")


def _details(issue: dict) -> str:
    """The detector's details for the prompts' data block, without a check's web `evidence`: a page's own words
    never reach the code-writing prompts raw (docs/plans/tavily.md §3.1 rule 4)."""
    return _json({k: v for k, v in (issue.get("details") or {}).items() if k != "evidence"}, 600)


def _instruction(issue: dict) -> str:
    """The user's instruction for the prompts' data block, or "none"."""
    return _safe(issue.get("instruction") or "none")


def _safe(text) -> str:
    """Text that goes inside a prompt's <data> block can't close it or open another (TRD §3.5, `escape_data`)."""
    return escape_data(text)


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
        plan = self.params.get("plan") or {}
        self.state.plan_id = plan.get("id")
        self.depth: int = plan.get("depth") or DEPTH  # the deepest layer the run attempts (PRD CLEAN-15)
        run = run_params(plan.get("items") or [])
        self.skip_keys = set(run["skip_keys"])
        self.instructions: dict[str, str] = run["instructions"]  # rewritten fixes, by issue key
        self.date_orders: dict[str, str] = run["date_orders"]     # the order picked for ambiguous dates, by key
        self.user_steps: list[dict] = run["user_steps"]           # in the plan's order
        self.levels: dict[str, str] = run["levels"]               # each listed fix's level, by key
        self.rules = rule_store.active(self.db, self.dataset["id"])  # the dataset's checks, re-run by the verifier
        self.item_ids = {i["key"]: i["id"] for i in plan.get("items") or [] if i["key"]}
        self.scope = CallScope(user_id=self.dataset["user_id"], dataset_id=self.dataset["id"], job_id=ctx.id,
                               on_wait=lambda text: ctx.log(text, level="warn", icon="wait"))
        self.work = self.settings.data_dir / ".clean" / ctx.id
        self.work.mkdir(parents=True, exist_ok=True)
        self.calls_after: int | None = None  # while an issue runs: the last `llm_calls` id before it
        self._meanings: dict[str, str] | None = None  # each column's note sentence, read once per run

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
        self.state.planned = min(s.clean_max_steps, self._planned())
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

    def _not_reached(self) -> None:
        """A run that ended on a budget: each issue it would still have attempted is skipped as `budget`,
        so the report lists what wasn't attempted (PRD CLEAN-6). By the queue's order, the least severe."""
        card = self._card()
        for issue in queue(card["issues"], card, self.levels):
            if key(issue) in self.state.handled or not self._attemptable(issue, card):
                continue
            self.state.handled.append(key(issue))
            self._skip(issue, f"Not reached: the run hit its {BUDGET_WORDS[self.state.ended_by]} budget", "budget",
                       log_text="not reached")

    def _finish(self) -> dict:
        if self.state.ended_by in BUDGET_WORDS:
            self._not_reached()
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

    def _attemptable(self, issue: dict, card: dict) -> bool:
        """Whether `_next_issue` would attempt the issue rather than skip it with no model call."""
        k = key(issue)
        return (never_change(issue, card) is None and k not in self.skip_keys and registry.within(issue, self.depth)
                and not (needs_order(issue) and k not in self.date_orders and k not in self.instructions))

    def _planned(self) -> int:
        """The issues the run expects to attempt, for the progress total: the user's steps, then one per
        key of the card's issues it would attempt. Fixes can expose more, or settle some before their turn."""
        card = self._card()
        return len(self.user_steps) + len({key(i) for i in card["issues"] if self._attemptable(i, card)})

    def _next_issue(self) -> dict | None:
        for step in self.user_steps:  # the user's own steps first, in the plan's order
            if f"user|{step['id']}" not in self.state.handled:
                return {"id": step["id"], "detector": USER_DETECTOR, "column": step["column"], "count": 0,
                        "severity": USER_SEVERITY, "proposal": step["instruction"], "examples": [], "details": {},
                        "user": True, "requested": True, "instruction": step["instruction"], "plan_item_id": step["id"]}
        card = self._card()
        for issue in queue(card["issues"], card, self.levels):
            if key(issue) in self.state.handled:
                continue
            if not registry.within(issue, self.depth):  # a layer the user didn't ask for: no model call
                self.state.handled.append(key(issue))
                self._skip(issue, TOO_DEEP, "unticked", log_text="deeper than your scan")
                continue
            # Columns that record the outcome or identify rows are marked, never changed, whatever the issue.
            kept = never_change(issue, card)
            if kept is not None:
                self.state.handled.append(key(issue))
                self._skip(issue, kept[0], "kept_by_design", log_text=registry.get(kept[1]).skip_text)
                continue
            if key(issue) in self.skip_keys:  # unticked in the plan: no model call, no budget used
                self.state.handled.append(key(issue))
                self._skip(issue, NOT_IN_PLAN, "unticked", log_text="not in your plan")
                continue
            if key(issue) in self.date_orders:  # the user picked the order: no vote
                order = self.date_orders[key(issue)]
                text = " ".join(t for t in (self.instructions.get(key(issue)), order_instruction(issue["column"], order)) if t)
                return {**issue, "requested": True, "instruction": text, "date_order": order,
                        "plan_item_id": self.item_ids.get(key(issue))}
            if needs_order(issue) and key(issue) not in self.instructions:  # every date reads both ways
                self.state.handled.append(key(issue))
                self._skip(issue, order_needed(issue), "needs_choice", log_text="needs your choice of order")
                continue
            if key(issue) in self.instructions:  # a fix the user rewrote
                return {**issue, "requested": True, "instruction": self.instructions[key(issue)],
                        "plan_item_id": self.item_ids.get(key(issue))}
            return issue
        return None

    def _outcome(self, issue: dict, outcome: str, reason: str | None = None, step: dict | None = None) -> None:
        """The outcome of a plan item, for the report's "Your steps"."""
        item_id = issue.get("plan_item_id") or self.item_ids.get(key(issue))
        if item_id is None:
            return
        out = {"outcome": outcome}
        if reason:
            out["reason"] = reason
        if step:
            out.update(step_id=step["id"], step_no=step["no"])
        self.state.plan_outcomes[item_id] = out

    def _skip(self, issue: dict, reason: str, kind: str, candidates=None, log_text: str | None = None,
              checks=None) -> None:
        """Skip an issue with its reason and its kind (`SKIP_KINDS`), which the report counts by."""
        level = None if issue.get("user") else (self.levels.get(key(issue)) or levels.default_level(issue, self._card()))
        self.state.skipped.append({"issue_id": issue["id"], "column": issue["column"], "detector": issue["detector"],
                                   "reason": reason, "skip_kind": kind, "level": level})
        self.db.execute("UPDATE issues SET outcome = 'skipped', skip_reason = ?, skip_kind = ? WHERE id = ?",
                        (reason, kind, issue["id"]))
        self._outcome(issue, "skipped", reason)
        self.ctx.log(reason, icon="skip", column=issue["column"], gate="skip", candidates=candidates,
                     detail=log_text or "skipped", issue_id=issue["id"], checks=checks, calls=self._calls())

    # --- one issue ------------------------------------------------------------------------------

    def _handle(self, issue: dict) -> None:
        self.calls_after = self.db.execute("SELECT COALESCE(MAX(id), 0) FROM llm_calls").fetchone()[0]
        try:
            self._attempt(issue)
        finally:
            self.calls_after = None

    def _calls(self) -> dict | None:
        """The model calls the running issue made so far, for its outcome line: how many, which models
        (in the order used), and their summed latency, from `llm_calls` by job."""
        if self.calls_after is None:
            return None
        rows = self.db.execute("SELECT model, latency_ms FROM llm_calls WHERE id > ? AND job_id = ? ORDER BY id",
                               (self.calls_after, self.ctx.id)).fetchall()
        if not rows:
            return None
        return {"count": len(rows), "models": list(dict.fromkeys(r["model"] for r in rows)),
                "latency_ms": sum(r["latency_ms"] or 0 for r in rows)}

    def _attempt(self, issue: dict) -> None:
        self.state.handled.append(run_key(issue))
        self.state.attempted += 1
        column = issue["column"]
        requested = bool(issue.get("requested"))
        rule = rule_candidate(issue)  # a domain rule (impossible values): no diagnosis or review leaves it be
        picked = order_candidate(issue)  # the date order the user picked: code's own parse settles it
        detector = None if issue.get("user") else issue["detector"]  # a user step has no detector to re-run
        # The total is the issues the run expected at its start; it grows only if a fix exposes more.
        self.ctx.progress(self.state.attempted, max(self.state.planned, self.state.attempted),
                          f"Step {self.state.attempted} · {column or 'rows'}")
        self.ctx.log(short_line(issue), icon="running", column=column, detail="checking candidates", issue_id=issue["id"])
        version, path = self._current_parquet()
        before = self._read(path)
        card = self._card()
        try:
            diagnosis = self._diagnose(issue, card, before)
        except StructuredOutputError:
            return self._skip(issue, "model output invalid", "model_error")
        fallback = code_fix(issue)  # numbers stored as text: the code's own parse when the model's fixes fail
        # Asked for, a domain rule, or numbers stored as text in a measure: "leave as is" doesn't end it.
        if diagnosis.leave_as_is and not requested and rule is None and not (fallback and measure_column(issue, card)):
            return self._skip(issue, f"Left as is: {prose(diagnosis.cause) or LEFT_AS_IS}", "left_as_is")
        try:
            proposed = list(self._propose(issue, diagnosis, before).candidates)
        except StructuredOutputError:  # a reply cut off at its token cap too (TRD §3.5)
            if rule is None and fallback is None and picked is None:
                return self._skip(issue, "model output invalid", "model_error")
            proposed = []
        if rule is not None:
            proposed.append(rule)
        if picked is not None:
            proposed.append(picked)
        sample_path = self.work / f"sample_{uuid.uuid4().hex}.parquet"
        _copy_rows(path, sample_path, self._sample_ids(before, issue))
        sample = self._read(sample_path)
        scored = []
        results: list[pd.DataFrame | None] = []  # each candidate's result on the sample, None when it failed

        def score(cand: Candidate) -> None:
            self.ctx.check_cancel()
            out = self.work / f"cand_{uuid.uuid4().hex}.parquet"
            r = sandbox.execute(self.settings, cand.code, sample_path, out, db=self.db,
                                dataset_id=self.dataset["id"], job_id=self.ctx.id,
                                should_stop=self._stop_requested)
            if r.cancelled:
                raise JobCancelled()
            if not r.ok:
                why = r.error or "the code failed"
                scored.append((cand, 0.0, None, f"{why} ({r.violations[0]})" if r.violations else why))
                results.append(None)
                return
            try:
                after = self._restrict(sample, self._read(out))
            except ScopeError as exc:
                scored.append((cand, 0.0, None, str(exc)))
                results.append(None)
                return
            report = verifiers.verify(sample, after, detector, column, requested=requested, rules=self.rules)
            scored.append((cand, report.score, report, None if report.passed else _first_failure(report)))
            results.append(after if report.passed else None)

        for cand in proposed:
            score(cand)
        width = len([c for c in sample.columns if c not in verifiers.SYSTEM])
        best_i = best_candidate(scored, width)
        if fallback is not None and (best_i is None or scored[best_i][1] == 0.0 or sets_aside_only(scored[best_i][2])):
            # The model gave no fix that passes (or none at all), or its best only sets rows aside: code's own
            # fix, which repairs without guessing, is scored too and wins a tie on the cells it touches.
            score(fallback)
            best_i = best_candidate(scored, width)
        settles = registry.get(issue["detector"]).code_fix_settles
        # Every value reads one way, so code's own parse isn't a guess (PRD CLEAN-4e).
        code_settles = fallback is not None and settles is not None and column in sample and settles(sample[column])
        chips = [{"label": c.label, "chosen": False} for c, *_ in scored]
        settled = picked is not None and scored[-1][1] > 0.0  # the user's order (last) is the fix
        if (rule is not None or picked is not None) and scored[-1][1] > 0.0:  # code's own fix beats a guessed value
            best_i = len(scored) - 1
        if best_i is None or scored[best_i][1] == 0.0:
            why = next((e for *_, e in scored if e), "no candidate passed the checks")
            return self._skip(issue, f"No candidate passed the checks ({why})", "failed_checks", candidates=chips)
        best, best_score, sample_report, _ = scored[best_i]
        chips[best_i]["chosen"] = True
        # Output agreement: candidates that pass but value the same cells differently leave
        # the data's answer open, so the step is skipped before the full run, with two cells both ways.
        compared = verifiers.compare(sample, results, best_i)
        apart = None if settled else gate.disagree(compared.disagreement)  # a picked order isn't a guess
        if apart and code_settles:
            # The model's fixes disagree, but code has its own parse (numbers stored as text, PRD CLEAN-4e)
            # and every value reads one way, so code's result isn't a guess: when it passes the checks it
            # settles the step. Values that read two ways ("1,250") keep the skip (CLEAN-4b).
            code_i = self._score_code_fix(score, scored, chips, fallback)
            if scored[code_i][1] > 0.0:
                chips[best_i]["chosen"], chips[code_i]["chosen"] = False, True
                best_i, apart = code_i, None
                best, best_score, sample_report, _ = scored[best_i]
        if apart:
            one, other = (scored[i][0].label for i in compared.pair)
            shown = "; ".join(f"{b} → {x} vs {y}" for b, x, y in compared.examples)
            return self._skip(issue, f"Skipped: {apart} ({one} vs {other}: {shown})", "disagreement", candidates=chips)

        # Code's own fix may stand in for a vetoed one only where it isn't a guess: always for a fix
        # without `code_fix_settles` (pairs, spellings), for a parse only when the values read one way.
        code_stands_in = fallback is not None and (settles is None or code_settles)
        while True:
            # The best candidate on the full data, verified again; the gate uses the real blast.
            self.ctx.check_cancel()
            full_out = self.work / f"full_{uuid.uuid4().hex}.parquet"
            r = sandbox.execute(self.settings, best.code, path, full_out, db=self.db,
                                dataset_id=self.dataset["id"], job_id=self.ctx.id,
                                should_stop=self._stop_requested)
            if r.cancelled:
                raise JobCancelled()
            if not r.ok:
                return self._skip(issue, f"Failed on the full data ({r.error})", "failed_checks", candidates=chips)
            try:
                after_full = self._restrict(before, self._read(full_out))
            except ScopeError as exc:
                return self._skip(issue, f"Not applied: {exc}", "failed_checks", candidates=chips)
            full_report = verifiers.verify(before, after_full, detector, column, requested=requested, rules=self.rules)
            if not full_report.passed:
                return self._skip(issue, f"Failed checks on the full data ({_first_failure(full_report)})", "failed_checks",
                                  candidates=chips, checks=full_report.hard)
            if full_report.cells_changed == 0 and full_report.quarantined == 0:
                return self._skip(issue, "The fix changed nothing", "failed_checks", candidates=chips)
            try:
                critique = self._critic(issue, best, before, after_full, full_report)
                review_ok = not critique.changed_something_it_shouldnt  # concerns alone don't count (gate.py)
            except StructuredOutputError:
                critique, review_ok = None, False
            if (critique is not None and critique.changed_something_it_shouldnt and code_stands_in
                    and best is not fallback and not (rule is not None and rule_only(full_report))):
                # The review vetoed the model's fix: code's own fix gets one turn in its place (TRD §7.2).
                code_i = self._score_code_fix(score, scored, chips, fallback)
                if scored[code_i][1] > 0.0:
                    chips[best_i]["chosen"], chips[code_i]["chosen"] = False, True
                    best_i = code_i
                    best, best_score, sample_report, _ = scored[best_i]
                    compared = verifiers.compare(sample, results, best_i)
                    continue
            break
        overruled = False
        if critique is not None and critique.changed_something_it_shouldnt:
            # The critic's verdict skips the step (owner's decision, 2026-10-25): its 0.2 share of the
            # confidence couldn't stop a commit with a flag (Day 3 review H2). Concerns alone still don't.
            # A domain rule's fix that only quarantines the rows the rule names is flagged instead: the
            # rule, not the model, says those values are impossible. So is code's own parse of values that
            # each read one way (CLEAN-4e): code, not the model, says what each number is.
            parse = code_settles and best is fallback
            if not (rule is not None and rule_only(full_report)) and not parse:
                said = next((c for c in critique.concerns if prose(c)), None)  # its first concern, as the flag shows it
                return self._skip(issue, "Skipped: the review found it changed values it shouldn't have"
                                  + (f" ({said.rstrip('.')})" if said else ""), "gate", candidates=chips,
                                  checks=full_report.hard)
            overruled = True
        user_cols = [c for c in before.columns if c not in verifiers.SYSTEM]
        total_cells = len(before) * max(len(user_cols), 1)
        affected = gate.cells_affected(full_report.cells_changed, full_report.quarantined, len(user_cols), total_cells)
        decision = gate.decide([s for _, s, *_ in scored], compared.agreement, review_ok, affected, total_cells,
                               requested=requested, domain_rule=rule is not None)
        if overruled:
            d = issue.get("details") or {}
            # The rule in words: a domain rule's own sentence, or a check's `words` (its `rule` is the spec).
            said = d["rule"] if isinstance(d.get("rule"), str) else d.get("words")
            decision = gate.overrule(decision, said) if rule is not None else gate.overrule_parse(decision)
        elif decision.gate == "commit" and (issue.get("details") or {}).get("review_pairs"):
            decision = gate.review(decision, issue["details"]["review_pairs"])
        if decision.gate == "skip":
            return self._skip(issue, f"Skipped: {decision.reason}", "gate", candidates=chips, checks=full_report.hard)
        restricted = full_out
        if self.allowed is not None or self.protected:
            restricted = self.work / f"commit_{uuid.uuid4().hex}.parquet"
            _write(after_full, restricted, _types(path))
        flag_reason = decision.reason if decision.gate == "flag" else None
        concerns = [c for c in (critique.concerns if critique else []) if prose(c)]
        if concerns and decision.gate == "flag":
            flag_reason = f"{decision.reason}; the review noted: {concerns[0]}"
        spec = StepSpec(
            kind="clean", summary=step_summary(best.label, column), created_by="cleaner",
            notebook_code=self._notebook_code(best.code), code=best.code, column_targets=[column] if column else [],
            helpers_used=[h for h in HELPER_NAMES if h + "(" in self._notebook_code(best.code)], confidence=decision.confidence,
            gate=decision.gate, flag_reason=flag_reason, parse_failures=full_report.quarantined,
            decisions=[{"question": (f"How to do what you asked in {column or 'the rows'}?" if issue.get("user") else
                                     f"How to fix {issue['detector'].replace('_', ' ')} in {column or 'the rows'}?"),
                        "chosen": best.label, "alternatives": [c.label for c, *_ in scored if c is not best],
                        "reason": prose(diagnosis.cause), "review": concerns,
                        **({"asked": issue["instruction"]} if requested else {}),
                        **({"evidence": evidence} if (evidence := self._evidence(issue)) else {})}],
            verifiers=full_report.as_json(), job_id=self.ctx.id,
        )
        try:
            step, _ = commit_step(Context(self.settings, self.db, self.ctx.cache, self.ctx.bus), self.dataset["id"],
                                  version, spec, lambda _old, out: shutil.copyfile(restricted, out))
        except ApiError as exc:
            if exc.status == 409:
                return self._skip(issue, "The data changed while this step ran", "conflict", candidates=chips)
            raise
        self.state.step_ids.append(step["id"])
        outcome = "fixed" if decision.gate == "commit" else "flagged"
        self.db.execute("UPDATE issues SET outcome = ?, handled_by_step_id = ? WHERE id = ?",
                        (outcome, step["id"], issue["id"]))
        self._outcome(issue, outcome, flag_reason, step)
        text = (f"committed · step {step['no']}" if decision.gate == "commit"
                else f"committed with a flag · step {step['no']} · confidence {decision.confidence:.2f}")
        # The line's numbers come from the full-data report; the model's sentence is a digit-free note.
        self.ctx.log(verifiers.effect_line(full_report, issue_words(issue)), icon="check" if decision.gate == "commit" else "flag",
                     column=column, gate=decision.gate, candidates=chips, step_id=step["id"], step_no=step["no"],
                     confidence=decision.confidence, detail=text, checks=full_report.hard, issue_id=issue["id"],
                     review=concerns, note=prose(best.expected_effect), calls=self._calls())

    def _stop_requested(self) -> bool:
        """Polled while a sandbox worker runs, so Stop kills it instead of waiting for it."""
        try:
            self.ctx.check_cancel()
            return False
        except JobCancelled:
            return True

    # --- model calls ----------------------------------------------------------------------------

    @staticmethod
    def _score_code_fix(score, scored: list, chips: list, fallback: Candidate) -> int:
        """The index of code's own fix in `scored`, scoring it (and adding its chip) if it wasn't yet."""
        if not any(c is fallback for c, *_ in scored):
            score(fallback)
            chips.append({"label": fallback.label, "chosen": False})
        return next(i for i, (c, *_) in enumerate(scored) if c is fallback)

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
        # An earlier step's decision may cite a page (`evidence`): its words stay out of the prompt (§3.1 rule 4).
        return {"entry": entry, "samples": samples,
                "decisions": [{k: v for k, v in d.items() if k != "evidence"} for ds in decisions for d in ds][:10],
                "meaning": self._meaning(column)}

    def _meaning(self, column: str | None) -> str | None:
        """The column's note sentence for the prompts (docs/plans/tavily.md §3.4, §3.1 rule 4): Super's digit-free
        `description`, never the source's `excerpt`, a dictionary's before one Sherlock found before the web's. One
        query per run; a missing table or row means no meaning, never a failed clean."""
        if self._meanings is None:
            self._meanings = {}
            try:
                for n in notes_for(self.db, self.dataset["id"], MEANING_KINDS):  # a column's best note first
                    text = " ".join(str(n["description"] or "").split())
                    if text:
                        self._meanings.setdefault(n["column"], text[:MEANING_CHARS])
            except sqlite3.Error:
                pass
        return self._meanings.get(column) if column else None

    def _evidence(self, issue: dict) -> dict | None:
        """The page a rule's check was taken from (docs/plans/tavily.md §3.3), for the step that enforces it:
        `{url, title, excerpt, retrieved_at}` from the rule's `spec_json`, or None for any other issue."""
        rule_id = (issue.get("details") or {}).get("rule_id")
        if issue.get("user") or not rule_id:
            return None
        rule = next((r for r in self.rules if r["id"] == rule_id), None)
        found = rule.get("evidence") if rule else None
        if not isinstance(found, dict) or not found.get("url"):
            return None
        return {k: found.get(k) for k in EVIDENCE_KEYS}

    def _track(self, completion) -> None:
        self.state.waited_for_model_s += completion.waited_s

    def _diagnose(self, issue: dict, card: dict, df: pd.DataFrame) -> Diagnosis:
        cc = self._column_context(issue, card, df)
        columns = ", ".join(f"{c['name']} ({c['type']})" for c in card["columns"])
        user = prompts.DIAGNOSE.format(
            issue_line=_safe(issue_line(issue)), detector=issue["detector"], column=_safe(issue["column"] or "(rows)"),
            rows=card["row_count"], columns=_safe(columns), column_card=_json(cc["entry"]), meaning=_safe(cc["meaning"] or "unknown"),
            samples=_json(cc["samples"]),
            examples=_json(cap_values(issue["examples"], 10)), details=_details(issue),
            decisions=_json(cc["decisions"], 1200) if cc["decisions"] else "none yet", instruction=_instruction(issue),
        )
        if registry.get(issue["detector"]).vote and not issue.get("date_order"):  # a picked order needs no vote
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
            issue_line=_safe(issue_line(issue)), column=_safe(column or "(rows)"), cause=_safe(diagnosis.cause),
            meaning=_safe(self._meaning(column) or "unknown"),
            approaches=_safe("; ".join(approaches)), dtypes=_json({c: str(t) for c, t in df.dtypes.items()}, 2000),
            samples=_json(samples), examples=_json(cap_values(issue["examples"], 10)), helpers=prompts.HELPERS,
            details=_details(issue), instruction=_instruction(issue),
        )
        out = self.llm.structured("large", self._messages(user), Candidates, purpose="propose", scope=self.scope,
                                  max_tokens=6000)
        self._track(out.completion)
        return out.value.model_copy(update={"candidates": [c.model_copy(update={"code": runnable(c.code)})
                                                           for c in out.value.candidates]})

    def _critic(self, issue, best, before: pd.DataFrame, after: pd.DataFrame, report) -> Critique:
        column = issue["column"]
        changes = []
        if column in before and column in after:
            b, a = before.set_index("_row_id")[column], after.set_index("_row_id")[column]
            diff = b.astype(str) != a.astype(str)
            for rid in list(b.index[diff])[:12]:
                changes.append(f"{b[rid]!r} → {a[rid]!r}")
        effect = (f"{report.cells_changed} cells changed, {report.unrelated_changed} outside {column}, "
                  f"{report.quarantined} rows quarantined")
        if not issue.get("user"):  # a user's step has no detector, so no count to compare
            effect += f"; the issue went from {report.issue_before} to {report.issue_after}"
        user = prompts.CRITIC.format(issue_line=_safe(issue_line(issue)), column=_safe(column or "(rows)"), label=_safe(best.label),
                                     code=_safe(best.code), effect=_safe(effect), changes=_json(changes), checks=_json(report.hard),
                                     meaning=_safe(self._meaning(column) or "unknown"), instruction=_instruction(issue))
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
        """Keep changes only to rows in scope and to cells nobody edited by hand
        (`keep_outside_scope`, which the step's notebook code repeats)."""
        if self.allowed is None and not self.protected:
            return after
        out = after.set_index("_row_id")
        b = before.set_index("_row_id")
        out_of_scope = [i for i in b.index if self.allowed is not None and i not in self.allowed]
        if out_of_scope:
            for c in [c for c in b.columns if c in out.columns]:
                if out[c].dtype != b[c].dtype and not b.loc[out_of_scope, c].equals(out.loc[out_of_scope, c]):
                    raise ScopeError(f"it changes the type of {c}, which can't be done for only some rows")
        for rid, col in self.protected:
            if rid in out.index and col in out.columns and str(out.at[rid, col]) != str(b.at[rid, col])                     and out[col].dtype == b[col].dtype:
                k = {"row_id": int(rid), "column": col}
                if k not in self.state.hand_edited_skipped:
                    self.state.hand_edited_skipped.append(k)
        return keep_outside_scope(before, after, self._scope_rows(), self._scope_cells())

    def _scope_rows(self) -> list[int] | None:
        return sorted(self.allowed) if self.allowed is not None else None

    def _scope_cells(self) -> list[tuple[int, str]]:
        return sorted(self.protected)

    def _notebook_code(self, code: str) -> str:
        """The step's code for the exported notebook and for replay: a scoped run repeats its scope."""
        lines = [code.rstrip()]
        if self.allowed is not None or self.protected:
            lines.append(f"result = keep_outside_scope(df, result, rows={self._scope_rows()!r}, "
                         f"cells={[tuple(c) for c in self._scope_cells()]!r})")
        return "\n".join(lines) + "\ndf = result\n"


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


def sets_aside_only(report) -> bool:
    """A passing fix that changes no value and only quarantines rows."""
    return report is not None and report.cells_changed == 0 and report.quarantined > 0


def best_candidate(scored: list[tuple], columns: int) -> int | None:
    """The index of the best of `scored` [(candidate, score, report, error)]: the highest score and, on
    equal scores, the one that touches the fewest cells, a quarantined row counting as all of its
    cells as in the gate's blast (`gate.cells_affected`): the most conservative fix of the same
    quality. None when nothing was scored."""
    if not scored:
        return None

    def touched(report) -> int:
        return report.cells_changed + report.quarantined * max(columns, 1) if report else 0

    return max(range(len(scored)), key=lambda i: (scored[i][1], -touched(scored[i][2])))


def _first_failure(report: verifiers.Report) -> str:
    for name, value in report.hard.items():
        if value != "pass":
            return f"{name}: {value.removeprefix('fail: ')}"
    return "checks failed"

