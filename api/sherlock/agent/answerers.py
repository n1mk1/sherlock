"""Answerers and actions for chat v1 (TRD §8.2, Implementation Plan D4.3): `ask_data`, `find_rows`,
`explain_widget`, `ask_history`, and the `create_widget` action. Each returns a result the composer
can cite and the sources that prove it. SQL from the model goes through the same validation as
widget SQL (TRD §6.3) and runs on the cached connection; a failure gets one repair with the error."""

import json
import re
import sqlite3
from dataclasses import dataclass, field

from sherlock.agent import prompts
from sherlock.db.util import new_id, now_iso
from sherlock.errors import ApiError
from sherlock.llm.client import CallScope, LLMClient, data_block
from sherlock.llm.schemas import PredicateDraft, SqlDraft, WidgetDraft
from sherlock.rows.query import ident
from sherlock.widgets import compile as wc
from sherlock.widgets import layout as wl
from sherlock.widgets import service as ws
from sherlock.widgets.execute import run_query

TABLE_ROWS = 20


class CantAnswer(Exception):
    """The answerer gave up with a message for the user (App Flow §10.2 failure modes)."""


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

    def _messages(self, user: str) -> list[dict]:
        return [{"role": "system", "content": prompts.SYSTEM}, {"role": "user", "content": user}]

    def _run(self, template: str, rid: str) -> Result:
        sql = wc.compile_sql(template, self.rows.rows())
        with ws.connection(self.env, self.dataset, self.dataset["current_version"]) as conn:
            out = run_query(conn, sql)
        return Result(rid, sql, template, out["columns"], out["rows"], out["row_count"], truncated=out["truncated"])

    @staticmethod
    def _read_as(res: Result, reading: str) -> Result:
        res.extra["reading"] = reading.strip()[:200]
        return res

    # --- ask_data ---------------------------------------------------------------------------

    def ask_data(self, question: str, rid: str) -> Result:
        messages = self._messages(prompts.SQL.format(context=self.context, message=data_block(question)))
        draft = self.llm.structured("medium", messages, SqlDraft, purpose="sql", scope=self.scope).value
        if not draft.answerable:
            raise CantAnswer(_closest(draft.closest))
        try:
            return self._read_as(self._run(draft.sql, rid), draft.reading)
        except ApiError as exc:
            repair = [*messages, {"role": "assistant", "content": json.dumps(draft.model_dump())},
                      {"role": "user", "content": prompts.SQL_REPAIR.format(error=exc.message)}]
            draft = self.llm.structured("medium", repair, SqlDraft, purpose="sql", scope=self.scope).value
            if not draft.answerable:
                raise CantAnswer(_closest(draft.closest)) from None
            try:
                return self._read_as(self._run(draft.sql, rid), draft.reading)
            except ApiError:
                raise CantAnswer("I couldn't build a working query for that. Try naming the column, "
                                 "e.g. 'average fare by pclass'.") from None

    # --- find_rows --------------------------------------------------------------------------

    def find_rows(self, question: str, rid: str, columns: list[str]) -> Result:
        messages = self._messages(prompts.PREDICATE.format(context=self.context, message=data_block(question)))
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
        messages = self._messages(prompts.WIDGET.format(context=self.context, message=data_block(request)))
        draft = self.llm.structured("medium", messages, WidgetDraft, purpose="widget", scope=self.scope).value
        try:
            return self._save_widget(draft, created_by)
        except ApiError as exc:
            repair = [*messages, {"role": "assistant", "content": json.dumps(draft.model_dump())},
                      {"role": "user", "content": prompts.SQL_REPAIR.format(error=exc.message)}]
            draft = self.llm.structured("medium", repair, WidgetDraft, purpose="widget", scope=self.scope).value
            try:
                return self._save_widget(draft, created_by)
            except ApiError:
                raise CantAnswer("I couldn't build a working query for that widget. Try naming the columns, "
                                 "e.g. 'a bar chart of average fare by embarked'.") from None

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
        messages = self._messages(prompts.UPDATE_WIDGET.format(widget=data_block(now), context=self.context,
                                                                message=data_block(request)))
        selection = ((spec.get("scope") or {}).get("rows") or {}).get("selection_id")
        draft = self.llm.structured("medium", messages, WidgetDraft, purpose="update_widget", scope=self.scope).value
        for attempt in range(2):
            try:
                row = ws.update(self.env, self.dataset, widget, self._spec(draft, selection), draft.title.strip() or None)
                self.reading = draft.reading.strip()[:200]
                return row
            except ApiError as exc:
                if attempt:
                    raise CantAnswer("I couldn't build a working query for that change. Try naming the columns.") from None
                repair = [*messages, {"role": "assistant", "content": json.dumps(draft.model_dump())},
                          {"role": "user", "content": prompts.SQL_REPAIR.format(error=exc.message)}]
                draft = self.llm.structured("medium", repair, WidgetDraft, purpose="update_widget", scope=self.scope).value
        raise AssertionError("unreachable")

    def _save_widget(self, draft: WidgetDraft, created_by: str) -> sqlite3.Row:
        spec = self._spec(draft, self.rows.selection_id)
        row = ws.create(self.env, self.dataset, spec, title=draft.title.strip() or None, created_by=created_by)
        self.reading = draft.reading.strip()[:200]
        saved = wl.stored(self.env.db, self.dataset["id"])
        if saved is not None:
            wl.save(self.env.db, self.dataset["id"], wl.append(saved, row["id"], draft.view))
        return row


def _closest(closest: str | None) -> str:
    text = "This file has no column that answers that."
    if closest:
        text += f" The closest I can answer: “{closest.strip()}”"
    return text


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
