"""Answerers and actions for chat v1 (TRD §8.2, Implementation Plan D4.3): `ask_data`, `find_rows`,
`explain_widget`, `ask_history`, and the `create_widget` action. Each returns a result the composer
can cite and the sources that prove it. SQL from the model goes through the same validation as
widget SQL (TRD §6.3) and runs on the cached connection; a failure gets one repair with the error.
A query that runs is checked in code (`findings`), and what code found goes back for one repair."""

import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field

from sqlglot import exp

from sherlock.agent import prompts
from sherlock.agent.resolve import candidates
from sherlock.db.util import new_id, now_iso
from sherlock.errors import ApiError
from sherlock.llm.client import BudgetExceeded, CallScope, LLMClient, LLMUnavailable, StructuredOutputError, fence
from sherlock.llm.schemas import PredicateDraft, SqlDraft, WidgetDraft
from sherlock.profile.service import MAX_INDEXED_VALUES
from sherlock.rows.query import ident
from sherlock.stories.wording import title_problem, wording_problem
from sherlock.widgets import compile as wc
from sherlock.widgets import layout as wl
from sherlock.widgets import service as ws
from sherlock.widgets.execute import run_query

log = logging.getLogger("sherlock.agent")
TABLE_ROWS = 20
SHOWN_VALUES = 8  # a finding about a literal lists this many of the column's values
NAMED_ROLES = ("dimension", "measure", "target_like", "time")  # a named column of these roles must be used


class CantAnswer(Exception):
    """The answerer gave up with a message for the user (App Flow §10.2 failure modes)."""


class Clarify(CantAnswer):
    """The answerer needs the user to pick one of two or three options first (PRD ASK-6). `means` says
    what each option stands for (`{"column": c}`, `{"value": [c, v]}`, `{"columns": [a, b]}` or
    `{"widget": id}`), so the choice resumes with the name resolved. Where a clarification can't be
    asked (the message already answers one, or another step answered), the message is the note."""

    def __init__(self, fallback: str, question: str, options: list[tuple[str, dict]], name: str | None = None) -> None:
        super().__init__(fallback)
        self.question, self.name = question, name
        self.options = [o for o, _ in options][:3]
        self.means = {o: m for o, m in options[:3]}

    def clarification(self) -> dict:
        return {"question": self.question, "options": self.options}


def reading_text(reading: str) -> str:
    """The model's reading as the source label shows it, or "" when it breaks the wording rules (plan 2.9)."""
    reading = (reading or "").strip()[:200]
    return "" if wording_problem(reading) else reading


@dataclass
class Scope:
    """Which rows a chat answer reads: the quarantine exclusion, the selection and the global filter."""
    selection: str | None = None
    selection_id: str | None = None
    global_filter: str | None = None
    words: str = "all usable rows"

    def rows(self, extra: str | None = None) -> str:
        return wc.rows_clause(extra, self.selection, self.global_filter)


@dataclass
class Result:
    id: str
    sql: str              # exactly what ran
    template: str         # the SQL with {{rows}}, for pinning
    columns: list[dict]
    rows: list[list]
    row_count: int
    total: int | None = None
    truncated: bool = False
    selection_id: str | None = None
    label: str | None = None
    extra: dict = field(default_factory=dict)

    def cell(self, r: int, c: int):
        return self.rows[r][c]

    def for_prompt(self, limit: int = 30) -> str:
        head = [c["name"] for c in self.columns]
        lines = [f"result {self.id}: {self.row_count} rows" + (f" of {self.total}" if self.total is not None else ""),
                 f"query: {' '.join(self.sql.split())}",
                 "columns: " + " | ".join(f"{i}:{n}" for i, n in enumerate(head))]
        for i, r in enumerate(self.rows[:limit]):
            lines.append(f"row {i}: " + " | ".join("null" if v is None else str(v)[:60] for v in r))
        if self.row_count > limit:
            lines.append(f"… {self.row_count - limit} more rows")
        return "\n".join(lines)


@dataclass
class Toolkit:
    env: ws.Env
    llm: LLMClient
    scope: CallScope
    dataset: sqlite3.Row
    context: str
    rows: Scope
    calls: list[int] = field(default_factory=lambda: [0])
    reading: str = ""  # how the last widget request's words were read as columns
    example: str = ""  # a question in this file's own columns, for "try naming the columns" (Rule 4)
    resolved: dict = field(default_factory=dict)  # the message's names (`resolve.resolve`), for the result checks
    types: dict = field(default_factory=dict)     # the file's columns and their DuckDB types
    roles: dict = field(default_factory=dict)     # the file's columns and their DataCard roles

    def _try_naming(self, what: str) -> str:
        return f"I couldn't build a working query for {what}. Try naming the columns" + (
            f", e.g. “{self.example}”." if self.example else ".")

    def _messages(self, user: str) -> list[dict]:
        return [{"role": "system", "content": prompts.SYSTEM}, {"role": "user", "content": user}]

    def _run(self, template: str, rid: str) -> Result:
        sql = wc.compile_sql(template, self.rows.rows())
        with ws.connection(self.env, self.dataset, self.dataset["current_version"]) as conn:
            out = run_query(conn, sql)
        return Result(rid, sql, template, out["columns"], out["rows"], out["row_count"], truncated=out["truncated"])

    @staticmethod
    def _read_as(res: Result, reading: str) -> Result:
        res.extra["reading"] = reading_text(reading)
        return res

    # --- ask_data ---------------------------------------------------------------------------

    def ask_data(self, question: str, rid: str) -> Result:
        messages = self._messages(prompts.SQL.format(context=self.context, message=fence(question)))
        draft = self.llm.structured("medium", messages, SqlDraft, purpose="sql", scope=self.scope).value
        if not draft.answerable:
            raise self._unanswered(self._closest(draft.closest))
        try:
            res = self._read_as(self._run(draft.sql, rid), draft.reading)
        except ApiError as exc:
            messages = [*messages, {"role": "assistant", "content": json.dumps(draft.model_dump())},
                        {"role": "user", "content": prompts.SQL_REPAIR.format(error=fence(exc.message))}]
            draft = self.llm.structured("medium", messages, SqlDraft, purpose="sql", scope=self.scope).value
            if not draft.answerable:
                raise self._unanswered(self._closest(draft.closest)) from None
            try:
                res = self._read_as(self._run(draft.sql, rid), draft.reading)
            except ApiError:
                raise self._unanswered(self._try_naming("that")) from None
        return self._checked(res, messages, draft, rid)

    def _checked(self, res: Result, messages: list[dict], draft: SqlDraft, rid: str) -> Result:
        """Plan 2.7: a result that ran is checked in code; what was found goes back for one repair. The
        repaired query replaces the first when it runs and shows no more findings; otherwise, or when the
        repair fails, the first result stands (it ran, and the question may really have no rows)."""
        found = self.findings(res, draft.sql)
        if not found:
            return res
        log.info("ask_data result check: %s", " | ".join(found))
        ask = [*messages, {"role": "assistant", "content": json.dumps(draft.model_dump())},
               {"role": "user", "content": prompts.RESULT_REPAIR.format(findings=fence("\n".join(f"- {f}" for f in found)))}]
        try:
            again = self.llm.structured("medium", ask, SqlDraft, purpose="sql_check", scope=self.scope).value
        except (StructuredOutputError, LLMUnavailable, BudgetExceeded):
            return res
        if not again.answerable or " ".join(again.sql.split()) == " ".join(draft.sql.split()):
            return res
        try:
            fixed = self._read_as(self._run(again.sql, rid), again.reading)
        except ApiError:
            return res
        left = self.findings(fixed, again.sql)
        log.info("ask_data result check: the repaired query %s (%d findings left)", "is kept" if len(left) <= len(found) else
                 "is dropped", len(left))
        return res if len(left) > len(found) else fixed

    def findings(self, res: Result, template: str) -> list[str]:
        """What code sees wrong with a result that ran (plan 2.7, TRD §8.1 step 5): no rows; a column of
        the result that is empty in every row; a column the message names (one that groups, measures or
        dates the rows) that the query never uses; and a text literal compared to a column whose values
        (the value index) don't include it."""
        out = []
        if res.row_count == 0:
            out.append("The query returned no rows.")
        else:
            out += [f"The result column {c['name']} is empty (null) in every row." for i, c in enumerate(res.columns)
                    if all(row[i] is None for row in res.rows)]
        try:
            tree = wc._parse_one(template.replace("{{rows}}", "TRUE"))
        except ApiError:
            return out
        by_lower = {c.lower(): c for c in self.types}
        used = {by_lower.get(c.name.lower()) for c in tree.find_all(exp.Column)}
        star = any(isinstance(e, exp.Star) for s in tree.find_all(exp.Select) for e in s.expressions)
        # A named column counts when it groups, measures or dates the rows: an ID or free-text column named
        # like the records ("how many reviews" → `review`) is the rows themselves, not a column to use.
        named = {col: text for text, col in (self.resolved.get("columns") or {}).items()
                 if self.roles.get(col) in NAMED_ROLES}
        named |= {cv[0]: text for text, cv in (self.resolved.get("values") or {}).items() if cv[0] not in named}
        if not star:
            out += [f"The question names {col} (“{text}”), but the query never uses that column."
                    for col, text in named.items() if col in self.types and col not in used]
        index = self._value_index()
        for col, literal in _compared_literals(tree):
            col = by_lower.get(col.lower())
            values = index.get(col) if col and self.types.get(col) == "VARCHAR" else None
            if not values or len(values) >= MAX_INDEXED_VALUES or literal in values:
                continue
            shown = ", ".join(f"'{v}'" for v in values[:SHOWN_VALUES]) + (", …" if len(values) > SHOWN_VALUES else "")
            out.append(f"{col} = '{literal}' matches no row: {col} has {shown}.")
        return out

    def _value_index(self) -> dict[str, list[str]]:
        """Each indexed column's values, most common first (the current version's value index)."""
        out: dict[str, list[str]] = {}
        for r in self.env.db.execute("SELECT column, value FROM value_index WHERE dataset_id = ? ORDER BY count DESC",
                                     (self.dataset["id"],)):
            out.setdefault(r["column"], []).append(r["value"])
        return out

    def _closest(self, closest: str | None) -> str:
        """ASK-8's honest limit with the model's closest question, or this file's own example when the
        model's breaks the wording rules (plan 2.9)."""
        closest = (closest or "").strip()
        if closest and wording_problem(closest):
            closest = self.example
        return _closest(closest)

    def _unanswered(self, fallback: str) -> CantAnswer:
        """A name the message used that nothing resolved, and that looks like one of the file's columns or
        values, becomes a clarification with its closest matches as buttons (plan 2.8, PRD ASK-6). Asked
        only when the query can't be written: a name the SQL step read correctly needs no question."""
        columns = list(self.types)
        for text in self.resolved.get("unresolved") or []:
            kind = (self.resolved.get("unresolved_kinds") or {}).get(text, "column")
            options = candidates(self.env.db, self.dataset["id"], text, kind, columns)
            if options:
                what = "column" if kind == "column" else "value"
                log.info("ask_data: asking which %s “%s” means: %s", what, text, ", ".join(o for o, _ in options))
                return Clarify(fallback, f"Which {what} do you mean by “{text}”?", options, name=text)
        return CantAnswer(fallback)

    # --- find_rows --------------------------------------------------------------------------

    def find_rows(self, question: str, rid: str, columns: list[str]) -> Result:
        messages = self._messages(prompts.PREDICATE.format(context=self.context, message=fence(question)))
        draft = self.llm.structured("medium", messages, PredicateDraft, purpose="predicate", scope=self.scope).value
        try:
            predicate = wc.validate_predicate(draft.predicate, columns)
        except ApiError as exc:
            raise CantAnswer(f"I couldn't turn that into a row filter ({exc.message})") from None
        rows_sql = self.rows.rows(predicate)
        cols = ", ".join(["_row_id", *[ident(c) for c in columns[:12]]])
        try:
            with ws.connection(self.env, self.dataset, self.dataset["current_version"]) as conn:
                total = conn.execute(f"SELECT count(*) FROM t WHERE {rows_sql}").fetchone()[0]
                sql = wc.validate_select(f"SELECT {cols} FROM t WHERE {rows_sql} ORDER BY _row_id LIMIT {TABLE_ROWS}")
                out = run_query(conn, sql)
        except Exception as exc:
            message = exc.message if isinstance(exc, ApiError) else str(exc)
            raise CantAnswer(f"I couldn't run that row filter ({message[:200]})") from None
        stored = predicate if not (self.rows.selection or self.rows.global_filter) else " AND ".join(
            f"({p})" for p in (predicate, self.rows.selection, self.rows.global_filter) if p)
        selection_id = new_id("sel")
        self.env.db.execute(
            "INSERT INTO selections (id, dataset_id, version, predicate, row_ids_json, row_count, label, created_at) "
            "VALUES (?, ?, ?, ?, NULL, ?, ?, ?)",
            (selection_id, self.dataset["id"], self.dataset["current_version"], stored, total, draft.label[:120], now_iso()),
        )
        template = f"SELECT {cols} FROM t WHERE {{{{rows}}}} AND ({predicate}) ORDER BY _row_id"
        return Result(rid, sql, template, out["columns"], out["rows"], out["row_count"], total=total,
                      selection_id=selection_id, label=draft.label)

    # --- create_widget ------------------------------------------------------------------------

    def create_widget(self, request: str, created_by: str = "chat") -> sqlite3.Row:
        messages = self._messages(prompts.WIDGET.format(context=self.context, message=fence(request)))
        draft = self.llm.structured("medium", messages, WidgetDraft, purpose="widget", scope=self.scope).value
        try:
            return self._save_widget(draft, created_by)
        except ApiError as exc:
            repair = [*messages, {"role": "assistant", "content": json.dumps(draft.model_dump())},
                      {"role": "user", "content": prompts.SQL_REPAIR.format(error=fence(exc.message))}]
            draft = self.llm.structured("medium", repair, WidgetDraft, purpose="widget", scope=self.scope).value
            try:
                return self._save_widget(draft, created_by)
            except ApiError:
                raise CantAnswer(self._try_naming("that widget")) from None

    def _spec(self, draft: WidgetDraft, selection_id: str | None) -> dict:
        options = {k: v for k, v in (("x", draft.x), ("y", draft.y)) if v}
        if draft.view == "kpi" and draft.y:
            options = {"value": draft.y}
        return {
            "scope": {"columns": {"x": draft.x, "y": draft.y},
                      "rows": {"predicate": None, "selection_id": selection_id, "inherit_global_filters": True}},
            "op": {"type": "sql", "sql": draft.sql},
            "view": {"type": draft.view, "options": options},
        }

    # --- update_widget (D8.5) ----------------------------------------------------------------

    def update_widget(self, request: str, widget: sqlite3.Row) -> sqlite3.Row:
        """Change a SQL widget as asked: `medium` returns the whole new widget (schema `WidgetDraft`),
        applied at once like an edit in the widget's menu, with its old spec kept for Undo."""
        spec = json.loads(widget["spec_json"])
        if spec["op"]["type"] != "sql":
            raise CantAnswer("That widget is an analysis; change it from its settings, or ask for a plain chart.")
        cols = (spec.get("scope") or {}).get("columns") or {}
        now = json.dumps({"title": widget["title"], "sql": spec["op"]["sql"], "view": spec["view"]["type"],
                          "x": cols.get("x"), "y": cols.get("y")})
        messages = self._messages(prompts.UPDATE_WIDGET.format(widget=fence(now), context=self.context,
                                                                message=fence(request)))
        selection = ((spec.get("scope") or {}).get("rows") or {}).get("selection_id")
        draft = self.llm.structured("medium", messages, WidgetDraft, purpose="update_widget", scope=self.scope).value
        for attempt in range(2):
            try:
                new = self._spec(draft, selection)
                row = ws.update(self.env, self.dataset, widget, new, widget_title(draft.title, new))
                self.reading = reading_text(draft.reading)
                return row
            except ApiError as exc:
                if attempt:
                    raise CantAnswer("I couldn't build a working query for that change. Try naming the columns.") from None
                repair = [*messages, {"role": "assistant", "content": json.dumps(draft.model_dump())},
                          {"role": "user", "content": prompts.SQL_REPAIR.format(error=fence(exc.message))}]
                draft = self.llm.structured("medium", repair, WidgetDraft, purpose="update_widget", scope=self.scope).value
        raise AssertionError("unreachable")

    def _save_widget(self, draft: WidgetDraft, created_by: str) -> sqlite3.Row:
        spec = self._spec(draft, self.rows.selection_id)
        row = ws.create(self.env, self.dataset, spec, title=widget_title(draft.title, spec), created_by=created_by)
        self.reading = reading_text(draft.reading)
        saved = wl.stored(self.env.db, self.dataset["id"])
        if saved is not None:
            wl.save(self.env.db, self.dataset["id"], wl.append(saved, row["id"], draft.view))
        return row


def _closest(closest: str | None) -> str:
    text = "This file has no column that answers that."
    if closest:
        text += f" The closest I can answer: “{closest.strip()}”"
    return text


def widget_title(title: str, spec: dict) -> str:
    """A chat widget's title: the model's when it passes the builder's title check and the wording check
    (plan 2.9, PRD STORY-3), otherwise the templated title from the spec, as the builder falls back."""
    title = (title or "").strip()
    return ws.templated_title(spec) if title_problem(title) else title


def _compared_literals(tree: exp.Expression) -> list[tuple[str, str]]:
    """(column, text) for each text literal the query compares a bare column with: `col = 'x'`,
    `col <> 'x'` and `col IN ('x', …)`. A column inside a function (`lower(col) = 'x'`) is left alone."""
    out = []
    for node in tree.find_all(exp.EQ, exp.NEQ):
        for a, b in ((node.this, node.expression), (node.expression, node.this)):
            if isinstance(a, exp.Column) and isinstance(b, exp.Literal) and b.is_string:
                out.append((a.name, b.this))
    for node in tree.find_all(exp.In):
        if isinstance(node.this, exp.Column):
            out += [(node.this.name, e.this) for e in node.expressions if isinstance(e, exp.Literal) and e.is_string]
    return out


# --- answerers without the model ------------------------------------------------------------


def explain_widget(env: ws.Env, dataset: sqlite3.Row, widget: sqlite3.Row, filters: list[dict]) -> dict:
    return ws.explain(env, dataset, widget, filters)


WORD = re.compile(r"[a-z0-9_]+")
STOP = {"the", "a", "an", "what", "did", "you", "do", "to", "of", "in", "on", "and", "or", "is", "was", "were", "how",
        "why", "which", "with", "for", "my", "me", "change", "changed", "data", "file", "column", "clean", "cleaning"}


def ask_history(db: sqlite3.Connection, dataset_id: str, question: str, effective: list[str]) -> list[dict]:
    """Steps whose summary, columns or decisions share words with the question (TRD §8.2). With no
    shared words, the latest steps."""
    words = {w for w in WORD.findall(question.lower()) if w not in STOP}
    rows = db.execute("SELECT * FROM steps WHERE dataset_id = ? ORDER BY no DESC", (dataset_id,)).fetchall()
    scored = []
    for r in rows:
        hay = " ".join([r["summary"], r["column_targets_json"], r["decisions_json"]]).lower()
        hits = sum(1 for w in words if w in WORD.findall(hay))
        scored.append((hits, r))
    matched = [r for hits, r in scored if hits] if words else []
    chosen = (matched or [r for _, r in scored])[:5]
    return [{"id": r["id"], "no": r["no"], "summary": r["summary"], "kind": r["kind"], "gate": r["gate"],
             "active": r["id"] in effective,
             "decisions": json.loads(r["decisions_json"])} for r in chosen]
