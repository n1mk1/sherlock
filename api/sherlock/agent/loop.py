"""The chat loop (TRD §8.1), version 1 (Implementation Plan D4.3).

Per message: context → route (`small`, schema `Route`, reasoning off) → clarification if ambiguous →
resolve names → run up to two intents → compose → verify → save the message with its focus. The
intents are `ask_data`, `find_rows`, `explain_widget`, `ask_history` and `create_widget` (D4.3), and
`ask_stats`, `ask_why`, `ask_model`, `ask_meaning` and `app_help` (D7.3, `insight.py`); each tab
exposes its own set (TRD §8.2), plus `edit_plan` while a cleaning plan is open (`context.plan_id`, PRD CLEAN-8b).
Intents that aren't built yet get an honest reply instead (ASK-8). Events go to `emit(type, data)` as they happen (§5.3), and
the message is saved even if nobody is listening any more.

Budgets per message: 8 answerer and action calls, `MESSAGE_TOKEN_BUDGET` tokens, 90 s.
"""

import json
import re
import sqlite3
import time
from collections.abc import Callable

from sherlock.agent import actions as acts
from sherlock.agent import flow, insight, prompts
from sherlock.agent.answerers import CantAnswer, Scope, Toolkit, ask_history, explain_widget
from sherlock.agent.compose import compose, runs_text, table_block, text_block
from sherlock.agent.resolve import resolve
from sherlock.db.util import new_id, now_iso
from sherlock.errors import ApiError
from sherlock.llm.client import BudgetExceeded, CallScope, LLMClient, LLMUnavailable, StructuredOutputError, fence
from sherlock.llm.schemas import Plan, Route
from sherlock.profile import service as profile_service
from sherlock.widgets import compile as wc
from sherlock.widgets import service as ws

MAX_CALLS = 8
WALL_S = 90.0
HISTORY = 6
CARD_CHARS = 16_000  # about 4k tokens
NOT_YET: dict[str, str] = {}
# Tool exposure by tab (TRD §8.2): the answerers everywhere, actions where they belong.
ANSWERERS = ("ask_data", "find_rows", "explain_widget", "ask_history", "ask_why", "ask_stats", "ask_model",
             "ask_meaning", "app_help")
TOOLS = {
    "dashboard": ANSWERERS + ("create_widget", "update_widget"),
    "csv": ANSWERERS + ("edit_cells", "clean_selection"),
    "flow": ANSWERERS + ("ask_story",),
}
PLAN_TOOLS = ("edit_plan",)  # added to the tab's tools while a cleaning plan is open (`context.plan_id`)
ELSEWHERE = {
    "create_widget": "Adding a widget works from the Dashboard tab; ask there, or use Add widget.",
    "update_widget": "Changing a widget works from the Dashboard tab.",
    "ask_story": "Questions about the story cards work from the Flow tab.",
    "edit_cells": "Changing cells from chat works from the CSV tab, where you can see them.",
    "clean_selection": "Cleaning from chat works from the CSV tab; select rows there, or use Clean with AI.",
    "edit_plan": "Changing a cleaning plan from chat works while the plan is open; press Clean with AI to open one.",
}
STEP_LABELS = {"ask_data": "Query the data", "find_rows": "Find the rows", "explain_widget": "Explain the widget",
               "ask_history": "Look at the history", "ask_why": "Find what drives it", "ask_stats": "Run a test",
               "ask_model": "Read the model card", "ask_meaning": "Look at the column", "app_help": "Look in the help",
               "create_widget": "Add a widget", "update_widget": "Change the widget", "ask_story": "Read the cards",
               "edit_cells": "Propose the edits", "clean_selection": "Propose a clean", "edit_plan": "Change the plan"}
SUMMARY_EVERY = 10  # older messages are folded into the running summary ten at a time (TRD §8.1 step 1)
DATA_INTENTS = ("ask_data", "find_rows")
INSIGHT = ("ask_stats", "ask_why", "ask_model", "ask_meaning", "app_help")
DASHBOARD_WORDS = re.compile(r"\b(dashboard|widget|pin)\b", re.I)
# A significance test only when the message asks about one: live (D8.4 eval), Nano sent "what is the
# overall survival rate?" and "what is the return rate?" to ask_stats.
STATS_WORDS = re.compile(r"\b(significan\w*|p[- ]?values?|statistic\w*|tests?|chance|random|correlat\w*|relat\w*|"
                         r"associat\w*|differen\w*|compare|versus|vs|between)\b", re.I)


def to_message(row: sqlite3.Row, db: sqlite3.Connection | None = None) -> dict:
    """A message in the TRD §4.9 `Message` shape (with its proposal when `db` is given)."""
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
    if row["proposal_id"] and db is not None:
        p = db.execute("SELECT * FROM proposals WHERE id = ?", (row["proposal_id"],)).fetchone()
        if p:
            out["proposal"] = acts.to_proposal(p)
    return out


def example_question(card: dict) -> str:
    """A question this file can answer, in its own columns ("the average <measure> by <group>"), or "".
    Examples in messages come from the file, never from the sample (Rule 4)."""
    cols = card["columns"]
    target = next((c["name"] for c in cols if c["role"] == "target_like"), None)
    measure = next((c["name"] for c in cols if c["role"] == "measure"), None)
    dim = next((c["name"] for c in cols if c["role"] == "dimension" and 2 <= (c["distinct"] or 0) <= 12), None)
    if (target or measure) and dim:
        return f"{'the rate of ' + target if target else 'the average ' + measure} by {dim}"
    return ""


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
    return f"The file has {card['row_count']} usable rows. Columns:\n" + fence("\n".join(lines))


class Agent:
    def __init__(self, env: ws.Env, llm: LLMClient, dataset: sqlite3.Row, emit: Callable[[str, dict], None]) -> None:
        self.env, self.llm, self.dataset, self.emit = env, llm, dataset, emit
        self.db = env.db
        self.started = time.monotonic()

    # --- persistence --------------------------------------------------------------------------

    def _save(self, mid: str, role: str, text: str, *, blocks=(), sources=(), context=None, focus=None,
              clarification=None, clarification_of=None, route=None, tokens=0, plan=None, proposal_id=None) -> dict:
        self.db.execute(
            "INSERT INTO messages (id, dataset_id, role, text, blocks_json, sources_json, context_json, focus_json, "
            "clarification_json, clarification_of, route_json, tokens_used, plan_json, proposal_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (mid, self.dataset["id"], role, text, json.dumps(list(blocks), default=str), json.dumps(list(sources)),
             json.dumps(context) if context is not None else None, json.dumps(focus, default=str) if focus else None,
             json.dumps(clarification) if clarification else None, clarification_of,
             json.dumps(route) if route else None, tokens, json.dumps(plan) if plan else None, proposal_id, now_iso()),
        )
        return to_message(self.db.execute("SELECT * FROM messages WHERE id = ?", (mid,)).fetchone(), self.db)

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
        # The scope's words carry a selection's label and a filter's values, and a title is the user's: fenced.
        parts = [card_summary(card), "Rows in scope ({{rows}} already applies this):\n" + fence(scope.words)]
        if context.get("focused_widget_id"):
            w = self.db.execute("SELECT title FROM widgets WHERE id = ?", (context["focused_widget_id"],)).fetchone()
            if w:
                parts.append("The user is looking at this widget:\n" + fence(w["title"]))
        if resolved and (resolved["columns"] or resolved["values"]):
            lines = [f"- “{k}” is column {v}" for k, v in resolved["columns"].items()]
            lines += [f"- “{k}” is the value '{v[1]}' of column {v[0]}" for k, v in resolved["values"].items()]
            parts.append("Names in the message:\n" + fence("\n".join(lines)))
        if focus and focus.get("question"):
            prev = f"Previous question: {focus['question']}"
            if focus.get("sql"):
                prev += f"\nIts query: {focus['sql']}"
            parts.append("Use this only if the message is incomplete on its own and continues it (like \"and only for "
                         "<a value>?\"); a message that makes sense by itself is a new question:\n" + fence(prev))
        summary = self.db.execute("SELECT summary FROM thread_summaries WHERE dataset_id = ?", (self.dataset["id"],)).fetchone()
        if summary:
            parts.append("Earlier in this conversation (a summary):\n" + fence(summary["summary"]))
        recent = [f"{r['role']}: {r['text'][:300]}" for r in history if r["text"]]
        if recent:
            parts.append("Recent messages:\n" + fence("\n".join(recent)))
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
        tools = TOOLS[tab] + (PLAN_TOOLS if context.get("plan_id") else ())
        if acts.EXPORT.search(question):
            return self._export(mid, question, context, scope)
        if tab == "flow" and flow.MAKE_SENSE.search(question):
            # "Make sense of this" on the canvas is the synthesis action; no routing call is needed.
            route = Route(intents=["ask_story"], ambiguous=False, clarification=None, multi_step=False, entities=[])
        else:
            route = self._route(question, base_context, scope, tools)
        if route.ambiguous and route.clarification and not clarified:
            clar = route.clarification.model_dump()
            self.emit("clarification", clar)
            out = self._save(mid, "assistant", clar["question"], clarification=clar, context=context,
                             route=route.model_dump(), tokens=scope.message_tokens[0])
            self.emit("message", out)
            return out

        resolved = resolve(self.db, dataset["id"], [e.model_dump() for e in route.entities], columns)
        ctx_text = self._context(card, rows_scope, history, focus, resolved, context)
        kit = Toolkit(self.env, self.llm, scope, dataset, ctx_text, rows_scope, example=example_question(card))
        blocks, sources, results, actions, notes, streamed, computed = [], [], [], [], [], [], []
        focus_out = {"question": question, "intents": list(route.intents), "selection_id": rows_scope.selection_id}

        intents = list(dict.fromkeys(route.intents[:2]))
        # Adding to the dashboard is an action, so it needs the user to ask for it: live, Nano added a
        # widget for "survival rate by sex as a chart" next to the answer despite the route prompt.
        if "create_widget" in intents and len(intents) > 1 and not DASHBOARD_WORDS.search(question):
            intents.remove("create_widget")
        if "ask_stats" in intents and not STATS_WORDS.search(question):
            intents = list(dict.fromkeys("ask_data" if i == "ask_stats" else i for i in intents))
        steps = [(i, question) for i in intents]
        if route.multi_step:
            steps = self._plan(question, ctx_text, scope, tools) or steps
        plan = [{"text": f"{STEP_LABELS.get(i, i)}: {q}" if q != question else STEP_LABELS.get(i, i), "status": "pending"}
                for i, q in steps] if len(steps) > 1 else None
        if plan:
            self.emit("plan", {"steps": plan})
        proposal = None
        for n, (intent, q) in enumerate(steps, 1):
            if kit.calls[0] >= MAX_CALLS or time.monotonic() - self.started > WALL_S:
                notes.append("I stopped early to stay within this answer's budget.")
                break
            kit.calls[0] += 1
            if plan:
                plan[n - 1]["status"] = "running"
                self.emit("plan.step", {"index": n - 1, "status": "running"})
            before = (len(blocks), len(results), len(notes))
            try:
                if intent not in tools:
                    raise CantAnswer(ELSEWHERE.get(intent, "I can't do that here."))
                if intent in INSIGHT:
                    rid = f"r{len(results) + len(computed) + 1}"
                    reply = self._insight(intent, kit, q, resolved, card, context, focus, rid)
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
                    res = kit.ask_data(q, rid) if intent == "ask_data" else kit.find_rows(q, rid, columns)
                    results.append(res)
                    streamed.append(table_block(res))
                    self.emit("block", streamed[-1])  # the first block, before the prose is written
                    label = f"Query ({res.id})" + (f", reading {res.extra['reading']}" if res.extra.get("reading") else "")
                    sources.append({"kind": "sql", "sql": res.sql, "label": label, "result": res.id})
                    if res.selection_id:
                        actions.append({"kind": "open_rows", "selection_id": res.selection_id})
                elif intent == "create_widget":
                    self.emit("status", {"text": "Building a widget"})
                    w = kit.create_widget(q)
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
                elif intent == "ask_story":
                    selected = [c for c in (context.get("selected_card_ids") or []) if isinstance(c, str)]
                    if flow.MAKE_SENSE.search(q):
                        self.emit("status", {"text": "Reading the selected cards"})
                        made, cited, card_out = flow.make_sense(self.db, self.env.bus, self.llm, scope, dataset, selected, columns)
                        blocks += made
                        sources += cited
                        focus_out["card_id"] = card_out["id"]
                    else:
                        self.emit("status", {"text": "Reading the story cards"})
                        made, cited = flow.ask_story(self.db, self.llm, scope, dataset, q, selected, columns)
                        blocks += made
                        sources += cited
                elif intent == "ask_history":
                    vrow = ws.version_row(self.db, dataset["id"], dataset["current_version"])
                    found = ask_history(self.db, dataset["id"], q, json.loads(vrow["effective_step_ids_json"]))
                    if not found:
                        raise CantAnswer("Nothing has changed this file yet.")
                    runs = []
                    for s in found:
                        runs.append({"type": "label", "ref": f"step:{s['id']}",
                                     "text": f"Step {s['no']}: {s['summary']}" + ("" if s["active"] else " (undone)")})
                        why = next((d.get("reason") for d in s["decisions"] if d.get("reason")), None)
                        if why:
                            runs.append({"type": "label", "ref": f"step:{s['id']}:reason", "text": f" — {why}"})
                        runs.append({"type": "text", "text": "\n"})
                    blocks.append({"type": "text", "body": {"blocks": [{"type": "bullets", "runs": runs}]}})
                    sources += [{"kind": "step", "step_id": s["id"], "label": f"Step {s['no']}"} for s in found]
                elif intent == "update_widget":
                    wid = context.get("focused_widget_id") or next(iter(resolved["widgets"].values()), None) or (focus or {}).get("widget_id")
                    w = self.db.execute("SELECT * FROM widgets WHERE id = ? AND dataset_id = ? AND deleted_at IS NULL",
                                        (wid, dataset["id"])).fetchone() if wid else None
                    if w is None:
                        raise CantAnswer("Which widget? Click one on the dashboard (it becomes the chat's context), or name it.")
                    self.emit("status", {"text": "Changing the widget"})
                    w = kit.update_widget(q, w)
                    spec = json.loads(w["spec_json"])
                    blocks.append(text_block([{"type": "text", "text": "I changed "},
                                              {"type": "label", "ref": f"widget:{w['id']}", "text": w["title"]},
                                              {"type": "text", "text": " on the dashboard. Undo puts it back."}]))
                    data = ws.data(self.env, dataset, w, [])
                    blocks.append({"type": "chart", "spec": spec, "data": data, "widget_id": w["id"]}
                                  if spec["view"]["type"] not in ("table", "kpi") else
                                  {"type": "table", "columns": data["columns"], "rows": data["rows"][:20], "total": data["row_count"],
                                   "widget_id": w["id"]})
                    sources.append({"kind": "sql", "sql": ws.explain(self.env, dataset, w, [])["sql"],
                                    "label": w["title"] + (f", reading {kit.reading}" if kit.reading else "")})
                    actions += [{"kind": "open_widget", "widget_id": w["id"]}, {"kind": "undo_widget", "widget_id": w["id"]}]
                    focus_out["widget_id"] = w["id"]
                elif intent == "edit_plan":
                    self.emit("status", {"text": "Changing the plan"})
                    summary = acts.edit_plan(kit, q, context)
                    blocks.append(text_block([{"type": "text", "text": summary}]))  # the panel follows plan.updated
                elif intent in ("edit_cells", "clean_selection"):
                    if proposal is not None:
                        raise CantAnswer("One change at a time: approve or reject the proposal above first.")
                    self.emit("status", {"text": "Working out the change"})
                    proposal = (acts.propose_edits(kit, q, context, types) if intent == "edit_cells"
                                else acts.propose_clean(self.db, dataset, context, mid))
                    self.emit("proposal", proposal)
                    blocks.append(text_block([{"type": "text", "text": "Nothing has changed yet. Approve to apply this, "
                                               "or reject it." if intent == "edit_cells" else
                                               "Approve to start Clean with AI; each fix it makes is a step you can undo."}]))
                else:
                    raise CantAnswer(NOT_YET.get(intent, "I can't do that yet."))
            except CantAnswer as exc:
                if str(exc) not in notes:
                    notes.append(str(exc))
            except StructuredOutputError:
                notes.append("I couldn't turn that into a query. Try naming the columns" +
                             (f", e.g. “{kit.example}”." if kit.example else "."))
            except ApiError as exc:
                if exc.code in ("llm_unavailable", "budget_exceeded"):
                    raise
                notes.append(exc.message)
            finally:  # also after an insight step's `continue`
                if plan:
                    ok = (len(blocks), len(results)) != before[:2] and len(notes) == before[2]
                    plan[n - 1]["status"] = "done" if ok else "failed"
                    self.emit("plan.step", {"index": n - 1, "status": plan[n - 1]["status"]})

        if results:
            self.emit("status", {"text": "Writing the answer"})
            known = {c["name"]: [v["value"] for v in c.get("top_values") or []] for c in card["columns"]}
            composed, _ = compose(self.llm, scope, question, results, columns, dataset["current_version"], rows_scope.selection_id,
                                  known)
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
        # Narrative answers with numbers can go on the canvas (PRD ASK-4); a synthesis is already there.
        if "card_id" not in focus_out:
            for i, b in enumerate(blocks):
                if b["type"] == "text" and b.get("labeled") != "general" and any(
                        r["type"] == "chip" and r.get("key") for p in b["body"]["blocks"] for r in p["runs"]):
                    actions.append({"kind": "add_to_flow", "block_index": i})
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
        if proposal and not text:
            text = proposal["summary"]
        out = self._save(mid, "assistant", text, blocks=blocks, sources=sources, context=context, focus=focus_out,
                         route=route.model_dump(), tokens=scope.message_tokens[0], plan={"steps": plan} if plan else None,
                         proposal_id=proposal["id"] if proposal else None)
        self.emit("message", out)
        self._summarize(scope)
        return out

    def _export(self, mid: str, question: str, context: dict, scope: CallScope) -> dict:
        """"Export a notebook" (App Flow §17.1): the dialog, with the options the wording asks for."""
        options = acts.export_options(question)
        said = {"include_data": "without the data", "include_cards": "without the story cards",
                "include_notes": "with the canvas notes", "include_runs": "without the analyses"}
        extra = [said[k] for k in options]
        text = "Here's the notebook export" + (f", {' and '.join(extra)}" if extra else "") + \
               ". Check the options and press Export; it downloads when it's ready."
        out = self._save(mid, "assistant", text, blocks=[text_block([{"type": "text", "text": text}])], context=context,
                         focus={"question": question, "intents": ["open_export"],
                                "actions": [{"kind": "open_export", "options": options}]})
        self.emit("message", out)
        return out

    def _plan(self, question: str, context: str, scope: CallScope, tools) -> list[tuple[str, str]] | None:
        """A message that asks for several things becomes two to five steps (TRD §8.1 step 4)."""
        intents = "\n".join(f"- {prompts.INTENT_LINES[i]}" for i in tools)
        messages = [{"role": "system", "content": prompts.SYSTEM},
                    {"role": "user", "content": prompts.PLAN.format(intents=intents, context=context, message=fence(question))}]
        try:
            plan = self.llm.structured("medium", messages, Plan, purpose="plan", scope=scope).value
        except (StructuredOutputError, LLMUnavailable, BudgetExceeded):
            return None
        steps = [(s.intent, s.question.strip() or question) for s in plan.steps if s.intent in tools]
        if "create_widget" in [i for i, _ in steps] and not DASHBOARD_WORDS.search(question):
            steps = [(i, q) for i, q in steps if i != "create_widget"]
        return steps[:5] if len(steps) >= 2 else None

    def _summarize(self, scope: CallScope) -> None:
        """Fold older messages into the running summary, ten at a time, with `small` (TRD §8.1 step 1).
        Best effort: a failure keeps the old summary."""
        row = self.db.execute("SELECT * FROM thread_summaries WHERE dataset_id = ?", (self.dataset["id"],)).fetchone()
        after = row["up_to_message_id"] if row else ""
        older = self.db.execute(
            "SELECT id, role, text FROM messages WHERE dataset_id = ? AND id > ? ORDER BY created_at, id",
            (self.dataset["id"], after)).fetchall()[:-HISTORY]  # the latest six stay in the context as they are
        if len(older) < SUMMARY_EVERY:
            return
        lines = "\n".join(f"{m['role']}: {m['text'][:300]}" for m in older)
        prompt = prompts.SUMMARY.format(previous=fence(row["summary"] if row else "none"), messages=fence(lines))
        try:
            c = self.llm.complete("small", [{"role": "system", "content": prompts.SYSTEM}, {"role": "user", "content": prompt}],
                                  purpose="summary", scope=scope, max_tokens=1500)
        except Exception:  # noqa: BLE001 - the summary is never worth failing an answer
            return
        summary = (c.text or "").strip()[:1500]
        if summary:
            self.db.execute("INSERT INTO thread_summaries (dataset_id, summary, up_to_message_id, updated_at) VALUES (?, ?, ?, ?) "
                            "ON CONFLICT(dataset_id) DO UPDATE SET summary = excluded.summary, "
                            "up_to_message_id = excluded.up_to_message_id, updated_at = excluded.updated_at",
                            (self.dataset["id"], summary, older[-1]["id"], now_iso()))

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
        example = example_question(card)
        if example:
            return f"Meanwhile I can break the data down, for example “{example}”."
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
                    {"role": "user", "content": prompts.ROUTE.format(intents=intents, context=context, message=fence(question))}]
        try:
            return self.llm.structured("small", messages, Route, purpose="route", scope=scope, reasoning=False).value
        except StructuredOutputError:
            # TRD §3.5: the router's fallback treats the message as a single ask_data question.
            return Route(intents=["ask_data"], ambiguous=False, clarification=None, multi_step=False, entities=[])
