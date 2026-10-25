"""The chat loop (TRD §8.1), version 1 (Implementation Plan D4.3).

Per message: context → route (`small`, schema `Route`, reasoning off) → clarification if ambiguous →
resolve names → run up to two intents → compose → verify → save the message with its focus. The
intents are `ask_data`, `find_rows`, `explain_widget`, `ask_history` and `create_widget` (D4.3), and
`ask_stats`, `ask_why`, `ask_model`, `ask_meaning` and `app_help` (D7.3, `insight.py`); each tab
exposes its own set (TRD §8.2). Intents that aren't built yet get an honest reply instead (ASK-8). Events go to `emit(type, data)` as they happen (§5.3), and
the message is saved even if nobody is listening any more.

Budgets per message: 8 answerer and action calls, `MESSAGE_TOKEN_BUDGET` tokens, 90 s.
"""

import json
import re
import sqlite3
import time
from collections.abc import Callable

from sherlock.agent import insight, prompts
from sherlock.agent.answerers import CantAnswer, Scope, Toolkit, ask_history, explain_widget
from sherlock.agent.compose import compose, runs_text, table_block, text_block
from sherlock.agent.resolve import resolve
from sherlock.db.util import new_id, now_iso
from sherlock.errors import ApiError
from sherlock.llm.client import BudgetExceeded, CallScope, LLMClient, LLMUnavailable, StructuredOutputError, data_block
from sherlock.llm.schemas import Route
from sherlock.profile import service as profile_service
from sherlock.widgets import compile as wc
from sherlock.widgets import service as ws

MAX_CALLS = 8
WALL_S = 90.0
HISTORY = 6
CARD_CHARS = 16_000  # about 4k tokens
NOT_YET = {
    "ask_story": "Answering from the story cards isn't built yet; each card's Ask why opens a question about it.",
    "update_widget": "Changing a widget from chat isn't built yet; use the widget's menu.",
}
# Tool exposure by tab (TRD §8.2): the answerers everywhere, actions where they belong.
ANSWERERS = ("ask_data", "find_rows", "explain_widget", "ask_history", "ask_why", "ask_stats", "ask_model",
             "ask_meaning", "app_help")
TOOLS = {
    "dashboard": ANSWERERS + ("create_widget", "update_widget"),
    "csv": ANSWERERS,
    "flow": ANSWERERS + ("ask_story",),
}
ELSEWHERE = {
    "create_widget": "Adding a widget works from the Dashboard tab; ask there, or use Add widget.",
    "update_widget": "Changing a widget works from the Dashboard tab.",
    "ask_story": "Questions about the story cards work from the Flow tab.",
}
DATA_INTENTS = ("ask_data", "find_rows")
INSIGHT = ("ask_stats", "ask_why", "ask_model", "ask_meaning", "app_help")
DASHBOARD_WORDS = re.compile(r"\b(dashboard|widget|pin)\b", re.I)


def to_message(row: sqlite3.Row) -> dict:
    """A message in the TRD §4.9 `Message` shape."""
    out = {
        "id": row["id"], "role": row["role"], "text": row["text"], "blocks": json.loads(row["blocks_json"]),
        "sources": json.loads(row["sources_json"]), "created_at": row["created_at"],
        "clarification_of": row["clarification_of"],
    }
    if row["clarification_json"]:
        out["clarification"] = json.loads(row["clarification_json"])
    if row["plan_json"]:
        out["plan"] = json.loads(row["plan_json"])
    focus = json.loads(row["focus_json"]) if row["focus_json"] else {}
    if focus.get("actions"):
        out["actions"] = focus["actions"]
    return out


def card_summary(card: dict) -> str:
    """Column names, types, roles and up to five example values; past the budget, the rest by name and type."""
    lines, used = [], 0
    for c in card["columns"]:
        examples = [str(v["value"]) for v in (c.get("top_values") or [])[:5]] or [str(v) for v in (c.get("sample_values") or [])[:5]]
        stats = c.get("stats") or {}
        rng = f" · range {stats['min']} to {stats['max']}" if c["type"] in ("int", "float", "date", "datetime") and "min" in stats else ""
        line = f"- {c['name']} · {c['type']} · {c['role']} · {c['missing_pct']}% missing{rng} · e.g. {', '.join(e[:40] for e in examples)}"
        if used + len(line) > CARD_CHARS:
            line = f"- {c['name']} · {c['type']}"
        lines.append(line)
        used += len(line)
    return f"The file has {card['row_count']} usable rows. Columns:\n" + data_block("\n".join(lines))


class Agent:
    def __init__(self, env: ws.Env, llm: LLMClient, dataset: sqlite3.Row, emit: Callable[[str, dict], None]) -> None:
        self.env, self.llm, self.dataset, self.emit = env, llm, dataset, emit
        self.db = env.db
        self.started = time.monotonic()

    # --- persistence --------------------------------------------------------------------------

    def _save(self, mid: str, role: str, text: str, *, blocks=(), sources=(), context=None, focus=None,
              clarification=None, clarification_of=None, route=None, tokens=0) -> dict:
        self.db.execute(
            "INSERT INTO messages (id, dataset_id, role, text, blocks_json, sources_json, context_json, focus_json, "
            "clarification_json, clarification_of, route_json, tokens_used, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (mid, self.dataset["id"], role, text, json.dumps(list(blocks), default=str), json.dumps(list(sources)),
             json.dumps(context) if context is not None else None, json.dumps(focus, default=str) if focus else None,
             json.dumps(clarification) if clarification else None, clarification_of,
             json.dumps(route) if route else None, tokens, now_iso()),
        )
        return to_message(self.db.execute("SELECT * FROM messages WHERE id = ?", (mid,)).fetchone())

    def _history(self) -> tuple[list[sqlite3.Row], dict | None]:
        rows = self.db.execute(
            "SELECT * FROM messages WHERE dataset_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (self.dataset["id"], HISTORY),
        ).fetchall()[::-1]
        focus = next((json.loads(r["focus_json"]) for r in reversed(rows) if r["role"] == "assistant" and r["focus_json"]), None)
        return rows, focus

    # --- context ------------------------------------------------------------------------------

    def _scope(self, context: dict, types: dict[str, str]) -> Scope:
        scope = Scope()
        words = []
        if context.get("selection_id"):
            scope.selection_id = context["selection_id"]
            scope.selection = ws.selection_sql(self.db, self.dataset["id"], context["selection_id"])
            n = self.db.execute("SELECT row_count, label FROM selections WHERE id = ?", (context["selection_id"],)).fetchone()
            words.append(f"the selection {n['label'] or ''} ({n['row_count']} rows)".replace("  ", " "))
        if context.get("global_filter"):
            scope.global_filter = wc.filter_sql(wc.parse_filter(context["global_filter"]), types)
            if scope.global_filter:
                words.append(f"rows where {scope.global_filter}")
        if words:
            scope.words = " and ".join(words)
        return scope

    def _context(self, card: dict, scope: Scope, history: list[sqlite3.Row], focus: dict | None, resolved: dict | None,
                 context: dict) -> str:
        parts = [card_summary(card), f"Rows in scope: {scope.words}. {{{{rows}}}} already applies this."]
        if context.get("focused_widget_id"):
            w = self.db.execute("SELECT title FROM widgets WHERE id = ?", (context["focused_widget_id"],)).fetchone()
            if w:
                parts.append(f"The user is looking at the widget “{w['title']}”.")
        if resolved and (resolved["columns"] or resolved["values"]):
            lines = [f"- “{k}” is column {v}" for k, v in resolved["columns"].items()]
            lines += [f"- “{k}” is the value '{v[1]}' of column {v[0]}" for k, v in resolved["values"].items()]
            parts.append("Names in the message:\n" + data_block("\n".join(lines)))
        if focus and focus.get("question"):
            prev = f"Previous question: {focus['question']}"
            if focus.get("sql"):
                prev += f"\nIts query: {focus['sql']}"
            parts.append("Use this only if the message is incomplete on its own and continues it (like \"and for women "
                         "only?\"); a message that makes sense by itself is a new question:\n" + data_block(prev))
        recent = [f"{r['role']}: {r['text'][:300]}" for r in history if r["text"]]
        if recent:
            parts.append("Recent messages:\n" + data_block("\n".join(recent)))
        return "\n\n".join(parts)

    # --- the loop -----------------------------------------------------------------------------

    def run(self, text: str, context: dict, clarification_of: str | None = None, choice: str | None = None) -> dict:
        dataset = self.dataset
        history, focus = self._history()
        user = self._save(new_id("msg"), "user", choice or text, context=context, clarification_of=clarification_of)
        mid = new_id("msg")
        scope = CallScope(user_id=dataset["user_id"], dataset_id=dataset["id"], message_id=mid,
                          on_wait=lambda t: self.emit("status", {"text": t}))
        question = text
        if clarification_of:
            asked = self.db.execute("SELECT * FROM messages WHERE id = ? AND dataset_id = ?", (clarification_of, dataset["id"])).fetchone()
            original = self.db.execute(
                "SELECT text FROM messages WHERE dataset_id = ? AND role = 'user' AND created_at <= ? AND id != ? "
                "ORDER BY created_at DESC, id DESC LIMIT 1", (dataset["id"], asked["created_at"] if asked else now_iso(), user["id"]),
            ).fetchone() if asked else None
            question = f"{original['text']}\n(Clarified: {choice or text})" if original else (choice or text)

        try:
            return self._answer(mid, question, context, scope, history, focus, clarified=bool(clarification_of))
        except (LLMUnavailable, BudgetExceeded) as exc:
            self.emit("error", {"code": exc.code, "message": exc.message})
            msg = "The model service is unavailable. Your data is safe; try again in a minute." if isinstance(exc, LLMUnavailable) else exc.message
            block = text_block([{"type": "text", "text": msg}])
            out = self._save(mid, "assistant", msg, blocks=[block], tokens=scope.message_tokens[0])
            self.emit("message", out)
            return out

    def _answer(self, mid: str, question: str, context: dict, scope: CallScope, history, focus, clarified: bool) -> dict:
        dataset = self.dataset
        self.emit("status", {"text": "Thinking…"})
        card = profile_service.get_or_build(self.env.settings, self.db, self.env.cache, dataset)
        types = ws.user_types(self.env, dataset, dataset["current_version"])
        columns = list(types)
        rows_scope = self._scope(context, types)
        base_context = self._context(card, rows_scope, history, focus, None, context)

        tab = context.get("tab") if context.get("tab") in TOOLS else "dashboard"
        route = self._route(question, base_context, scope, TOOLS[tab])
        if route.ambiguous and route.clarification and not clarified:
            clar = route.clarification.model_dump()
            self.emit("clarification", clar)
            out = self._save(mid, "assistant", clar["question"], clarification=clar, context=context,
                             route=route.model_dump(), tokens=scope.message_tokens[0])
            self.emit("message", out)
            return out

        resolved = resolve(self.db, dataset["id"], [e.model_dump() for e in route.entities], columns)
        ctx_text = self._context(card, rows_scope, history, focus, resolved, context)
        kit = Toolkit(self.env, self.llm, scope, dataset, ctx_text, rows_scope)
        blocks, sources, results, actions, notes, streamed, computed = [], [], [], [], [], [], []
        focus_out = {"question": question, "intents": list(route.intents), "selection_id": rows_scope.selection_id}

        intents = list(dict.fromkeys(route.intents[:2]))
        # Adding to the dashboard is an action, so it needs the user to ask for it: live, Nano added a
        # widget for "survival rate by sex as a chart" next to the answer despite the route prompt.
        if "create_widget" in intents and len(intents) > 1 and not DASHBOARD_WORDS.search(question):
            intents.remove("create_widget")
        for n, intent in enumerate(intents, 1):
            if kit.calls[0] >= MAX_CALLS or time.monotonic() - self.started > WALL_S:
                notes.append("I stopped early to stay within this answer's budget.")
                break
            kit.calls[0] += 1
            try:
                if intent not in TOOLS[tab]:
                    raise CantAnswer(ELSEWHERE.get(intent, "I can't do that here."))
                if intent in INSIGHT:
                    rid = f"r{len(results) + len(computed) + 1}"
                    reply = self._insight(intent, kit, question, resolved, card, context, focus, rid)
                    blocks += reply.blocks
                    sources += reply.sources
                    actions += reply.actions
                    results += reply.results
                    computed += [r.id for r in reply.results]
                    focus_out.update(reply.focus)
                    continue
                if intent in ("ask_data", "find_rows"):
                    self.emit("status", {"text": "Running a query" if intent == "ask_data" else "Finding rows"})
                    rid = f"r{len(results) + len(computed) + 1}"
                    res = kit.ask_data(question, rid) if intent == "ask_data" else kit.find_rows(question, rid, columns)
                    results.append(res)
                    streamed.append(table_block(res))
                    self.emit("block", streamed[-1])  # the first block, before the prose is written
                    label = f"Query ({res.id})" + (f", reading {res.extra['reading']}" if res.extra.get("reading") else "")
                    sources.append({"kind": "sql", "sql": res.sql, "label": label, "result": res.id})
                    if res.selection_id:
                        actions.append({"kind": "open_rows", "selection_id": res.selection_id})
                elif intent == "create_widget":
                    self.emit("status", {"text": "Building a widget"})
                    w = kit.create_widget(question)
                    data = ws.data(self.env, dataset, w, [])
                    spec = json.loads(w["spec_json"])
                    blocks.append(text_block([{"type": "text", "text": "I added "},
                                              {"type": "label", "ref": f"widget:{w['id']}", "text": w["title"]},
                                              {"type": "text", "text": " to the dashboard."}]))
                    blocks.append({"type": "chart" if spec["view"]["type"] not in ("table", "kpi") else "table",
                                   **({"spec": spec, "data": data} if spec["view"]["type"] not in ("table", "kpi") else
                                      {"columns": data["columns"], "rows": data["rows"][:20], "total": data["row_count"]}),
                                   "widget_id": w["id"]})
                    label = w["title"] + (f", reading {kit.reading}" if kit.reading else "")
                    sources.append({"kind": "sql", "sql": ws.explain(self.env, dataset, w, [])["sql"], "label": label})
                    actions.append({"kind": "open_widget", "widget_id": w["id"]})
                    focus_out["widget_id"] = w["id"]
                elif intent == "explain_widget":
                    wid = context.get("focused_widget_id") or next(iter(resolved["widgets"].values()), None)
                    w = self.db.execute("SELECT * FROM widgets WHERE id = ? AND dataset_id = ? AND deleted_at IS NULL",
                                        (wid, dataset["id"])).fetchone() if wid else None
                    if w is None:
                        raise CantAnswer("Which widget? Point at one on the dashboard, or name it.")
                    ex = explain_widget(self.env, dataset, w, wc.parse_filter(context.get("global_filter")))
                    blocks.append(text_block([{"type": "label", "ref": f"widget:{w['id']}", "text": w["title"]},
                                              {"type": "text", "text": " runs the query below on the current version, "
                                               "leaving out quarantined rows."}]))
                    sources.append({"kind": "sql", "sql": ex.get("sql"), "label": w["title"]})
                    actions.append({"kind": "open_widget", "widget_id": w["id"]})
                elif intent == "ask_history":
                    vrow = ws.version_row(self.db, dataset["id"], dataset["current_version"])
                    steps = ask_history(self.db, dataset["id"], question, json.loads(vrow["effective_step_ids_json"]))
                    if not steps:
                        raise CantAnswer("Nothing has changed this file yet.")
                    runs = []
                    for s in steps:
                        runs.append({"type": "label", "ref": f"step:{s['id']}",
                                     "text": f"Step {s['no']}: {s['summary']}" + ("" if s["active"] else " (undone)")})
                        why = next((d.get("reason") for d in s["decisions"] if d.get("reason")), None)
                        if why:
                            runs.append({"type": "label", "ref": f"step:{s['id']}:reason", "text": f" — {why}"})
                        runs.append({"type": "text", "text": "\n"})
                    blocks.append({"type": "text", "body": {"blocks": [{"type": "bullets", "runs": runs}]}})
                    sources += [{"kind": "step", "step_id": s["id"], "label": f"Step {s['no']}"} for s in steps]
                else:
                    raise CantAnswer(NOT_YET.get(intent, "I can't do that yet."))
            except CantAnswer as exc:
                if str(exc) not in notes:
                    notes.append(str(exc))
            except StructuredOutputError:
                notes.append("I couldn't turn that into a query. Try naming the column, e.g. 'average fare by pclass'.")
            except ApiError as exc:
                if exc.code in ("llm_unavailable", "budget_exceeded"):
                    raise
                notes.append(exc.message)

        if results:
            self.emit("status", {"text": "Writing the answer"})
            composed, _ = compose(self.llm, scope, question, results, columns, dataset["current_version"], rows_scope.selection_id)
            by_id = {r.id: r for r in results}
            # A model card's numbers have no query to pin: shown as a table, never a pinnable chart.
            composed = [table_block(by_id[b["result"]]) if b["type"] == "chart" and b.get("result") in computed else b
                        for b in composed]
            # Of a model card's tables, show only those the prose cites.
            cited = {r.get("key", "").split(":")[0] for b in composed if b["type"] == "text"
                     for para in b["body"]["blocks"] for r in para["runs"] if r["type"] == "chip"}
            composed = [b for b in composed if not (b["type"] == "table" and b.get("result") in computed and b["result"] not in cited)]
            blocks = composed + blocks
            for i, b in enumerate(blocks):
                if b["type"] == "chart" and "widget_id" not in b:
                    actions.append({"kind": "pin", "block_index": i})
            queried = [r for r in results if r.id not in computed]
            if queried:
                focus_out.update({"sql": queried[0].template, "columns": [c["name"] for c in queried[0].columns]})
            focus_out["result_ids"] = [r.id for r in results]
        if notes and not blocks and any(n in NOT_YET.values() for n in notes):
            notes.append(self._suggestion(card))  # ASK-8: say what is answerable instead
        for note in notes:
            blocks.append(text_block([{"type": "text", "text": note}]))
        for b in blocks:
            if b not in streamed:
                self.emit("block", b)
        if sources:
            self.emit("sources", {"sources": sources})
        text = " ".join(runs_text(p["runs"]) for b in blocks if b["type"] == "text" for p in b["body"]["blocks"]).strip()
        if not text:
            number = next((b for b in blocks if b["type"] == "number"), None)
            if number:
                text = f"{number['label']}: {number['formatted']}"
            elif results:
                text = f"Here is the result ({results[0].row_count} rows)."
        unique = []
        for a in actions:  # two intents may offer the same action
            if a not in unique:
                unique.append(a)
        actions = unique
        focus_out["actions"] = actions
        out = self._save(mid, "assistant", text, blocks=blocks, sources=sources, context=context, focus=focus_out,
                         route=route.model_dump(), tokens=scope.message_tokens[0])
        self.emit("message", out)
        return out

    def _insight(self, intent: str, kit: Toolkit, question: str, resolved: dict, card: dict, context: dict,
                 focus: dict | None, rid: str) -> "insight.Reply":
        status = {"ask_stats": "Running a test", "ask_why": "Finding what drives it", "ask_model": "Reading the model card",
                  "ask_meaning": "Looking at the column", "app_help": "Looking in the help"}[intent]
        self.emit("status", {"text": status})
        if intent == "ask_stats":
            return insight.ask_stats(kit, question, resolved, card, rid)
        if intent == "ask_why":
            left = WALL_S - (time.monotonic() - self.started) - 15
            filters = wc.parse_filter(context.get("global_filter"))
            return insight.ask_why(kit, question, resolved, card, filters, rid, wait_s=max(0.0, min(insight.WAIT_S, left)),
                                   status=lambda t: self.emit("status", {"text": t}))
        if intent == "ask_model":
            return insight.ask_model(kit, question, resolved, context, focus, rid)
        if intent == "ask_meaning":
            return insight.ask_meaning(kit, question, resolved, card, rid)
        return insight.app_help(question)

    @staticmethod
    def _suggestion(card: dict) -> str:
        """The closest answerable kind of question, with this file's own columns."""
        cols = card["columns"]
        target = next((c["name"] for c in cols if c["role"] == "target_like"), None)
        measure = next((c["name"] for c in cols if c["role"] == "measure"), None)
        dim = next((c["name"] for c in cols if c["role"] == "dimension" and 2 <= (c["distinct"] or 0) <= 12), None)
        if (target or measure) and dim:
            what = f"the rate of {target}" if target else f"the average {measure}"
            return f"Meanwhile I can break the data down, for example “{what} by {dim}”."
        return "Meanwhile I can answer questions about the data, find rows, explain a widget, or add one."

    def create_widget(self, prompt: str, created_by: str = "user") -> sqlite3.Row:
        """`POST /widgets` with `{ prompt }` (the Add widget drawer's "Describe it"): the same
        `create_widget` action as chat, without a thread message. Raises CantAnswer."""
        dataset = self.dataset
        scope = CallScope(user_id=dataset["user_id"], dataset_id=dataset["id"], message_id=new_id("msg"))
        card = profile_service.get_or_build(self.env.settings, self.db, self.env.cache, dataset)
        context = self._context(card, Scope(), [], None, None, {})
        return Toolkit(self.env, self.llm, scope, dataset, context, Scope()).create_widget(prompt, created_by)

    def _route(self, question: str, context: str, scope: CallScope, tools=TOOLS["dashboard"]) -> Route:
        intents = "\n".join(f"- {prompts.INTENT_LINES[i]}" for i in tools)
        messages = [{"role": "system", "content": prompts.SYSTEM},
                    {"role": "user", "content": prompts.ROUTE.format(intents=intents, context=context, message=data_block(question))}]
        try:
            return self.llm.structured("small", messages, Route, purpose="route", scope=scope, reasoning=False).value
        except StructuredOutputError:
            # TRD §3.5: the router's fallback treats the message as a single ask_data question.
            return Route(intents=["ask_data"], ambiguous=False, clarification=None, multi_step=False, entities=[])
