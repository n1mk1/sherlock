"""The chat loop (TRD §8.1), version 1 (Implementation Plan D4.3).

Per message: context → route (`small`, schema `Route`, reasoning off) → clarification if ambiguous →
resolve names → run up to two intents → compose → verify → save the message with its focus. The
intents are `ask_data`, `find_rows` and `ask_history` (D4.3), `ask_stats`, `ask_why`, `ask_model`, `ask_meaning`
and `app_help` (D7.3, `insight.py`), `web_context` (outside-world questions answered from a web search, PRD
ASK-11, `web.py`), `ask_code` (questions SQL can't express, as read-only pandas, `analysis.py`), and the actions
`edit_cells`, `clean_step` (a cleaning command: pandas code the user reads, then runs with OK, `commands.py`) and
`clean_selection` (TRD §8.2), plus `edit_plan` while a cleaning plan is open (`context.plan_id`, PRD CLEAN-8b).
A dated answer with a clear jump also offers "What happened around <period>?", and its press is a dated news search
(`period.py`, docs/plans/tavily.md §3.6). Intents that aren't built yet get an honest reply instead (ASK-8). Events go to `emit(type, data)` as they happen (§5.3), and
the message is saved even if nobody is listening any more.

Budgets per message: 8 answerer and action calls, `MESSAGE_TOKEN_BUDGET` tokens, 90 s.
"""

import json
import re
import sqlite3
import time
from collections.abc import Callable

from sherlock.agent import actions as acts
from sherlock.agent import analysis, commands
from sherlock.agent import insight, period, prompts
from sherlock.agent import web as aw
from sherlock.agent.answerers import CantAnswer, Clarify, Scope, Toolkit, ask_history, stem_linked
from sherlock.agent.compose import compose, runs_text, table_block, text_block
from sherlock.agent.resolve import drop_counts, resolve
from sherlock.db.util import new_id, now_iso
from sherlock.errors import ApiError
from sherlock.llm.client import (
    BudgetExceeded, CallScope, DeadlineExceeded, LLMClient, LLMUnavailable, StructuredOutputError, fence,
)
from sherlock.llm.schemas import Plan, Route
from sherlock.profile import service as profile_service
from sherlock.llm.wording import wording_problem
from sherlock.query import context as qx
from sherlock.web.client import WebClient

MAX_CALLS = 8
WALL_S = 90.0
HISTORY = 6
CARD_CHARS = 16_000  # about 4k tokens
NOT_YET: dict[str, str] = {}
# The tools (TRD §8.2): the answerers, then the actions. A cell edit and a clean of the selection are proposals.
ANSWERERS = ("ask_data", "find_rows", "ask_history", "ask_why", "ask_stats", "ask_model", "ask_meaning", "app_help",
             "web_context")
TOOLS = ANSWERERS + ("ask_code", "edit_cells", "clean_step", "clean_selection")
PLAN_TOOLS = ("edit_plan",)  # added to the tools while a cleaning plan is open (`context.plan_id`)
ELSEWHERE = {
    "edit_plan": "Changing a cleaning plan from chat works while the plan is open; press Clean with AI to open one.",
}
STEP_LABELS = {"ask_data": "Query the data", "find_rows": "Find the rows",
               "ask_history": "Look at the history", "ask_why": "Find what drives it", "ask_stats": "Run a test",
               "ask_model": "Read the model card", "ask_meaning": "Look at the column", "app_help": "Look in the help",
               "edit_cells": "Propose the edits", "clean_step": "Write the change", "clean_selection": "Propose a clean",
               "edit_plan": "Change the plan", "ask_code": "Work it out in code"}
SUMMARY_EVERY = 10  # older messages are folded into the running summary ten at a time (TRD §8.1 step 1)
INSIGHT = ("ask_stats", "ask_why", "ask_model", "ask_meaning", "app_help", "web_context")
# A significance test only when the message asks about one: live (D8.4 eval), Nano sent "what is the
# overall survival rate?" and "what is the return rate?" to ask_stats.
# The cleaning history only when the message is about what changed in the file: live, Nano sent
# "historically, what were <two ports>?" to ask_history.
HISTORY_WORDS = re.compile(r"\b(clean\w*|edit\w*|chang\w*|step\w*|undo\w*|undid|fix\w*|did you|you did|done to|happen\w*|"
                           r"modif\w*|replac\w*|quarantin\w*|remov\w*|fill\w*|typed|why)\b", re.I)
# A column's meaning only when the message asks what something means or is: live, Nano sent "what did
# a <column word> on <something> usually include?" to ask_meaning.
MEANING_WORDS = re.compile(r"\b(mean\w*|stand\w*|represent\w*|refer\w*|defin\w*|describ\w*|explain\w*|what is|what's|"
                           r"what are|what kind|what type|code\w*|abbreviat\w*|unit\w*|column\w*|field\w*|tell me about)\b", re.I)
STATS_WORDS = re.compile(r"\b(significan\w*|p[- ]?values?|statistic\w*|tests?|chance|random|correlat\w*|relat\w*|"
                         r"associat\w*|differen\w*|compare|versus|vs|between)\b", re.I)
# Guards on the route (TRD §8.1), each from a live miss (the end-to-end test of 2026-10-26):
# A ranking needs ORDER BY and LIMIT, which a row filter can't hold: "list the 5 <records> who paid the highest
# <a column>" went to find_rows and listed every row.
RANKING = re.compile(r"\b(top|bottom)\s+(\d+|two|three|four|five|six|seven|eight|nine|ten|twenty|fifty|hundred)\b|"
                     r"\b(highest|lowest|largest|smallest|biggest|greatest|oldest|youngest|longest|shortest|cheapest|"
                     r"earliest|latest|newest|most|least|best|worst)\b", re.I)
# A question about the quarantine itself: "why were some rows quarantined?" went to ask_why, "how many rows are
# quarantined and why?" to ask_data, which reads only usable rows.
QUARANTINE_ASK = re.compile(r"\b(why|reasons?|how many|number of|count)\b[^.?!]*\bquarantin\w*|\bquarantin\w*[^.?!]*\b(why|reasons?)\b|"
                            r"\b(which|what)\b[^.?!]*\b(are|were|is|was|got|been)\s+quarantin\w*", re.I)
# How to use the app: "how do I undo a cleaning step?" went to ask_history, "how do I re-run …" to ask_model.
HOW_TO = re.compile(r"^\W*(how|where)\s+(do|can|could|should)\s+(i|we)\b|^\W*how\s+to\b", re.I)
# A what-if is a question, never a change: live (commands eval), "what would happen if I upper-cased <a column>?"
# made a card.
WHAT_IF = re.compile(r"^\W*(what\s+(would|will|might)\s+(happen|change)|what\s+if)\b", re.I)
# An explicit web search: "search the web for what happened to <someone>" went to ask_history ("happened").
WEB_ASK = re.compile(r"\b(search|look\s+up|google)\b[^.?!]*\b(web|internet|online)\b|\b(on|from)\s+the\s+(web|internet)\b", re.I)
# A request to delete or remove rows or columns is a command: the user reads the code and the count before it runs,
# and Undo brings them back. Live, "delete all the <records> …" only listed them.
DELETE_ASK = re.compile(r"^\W*(please\s+)?((can|could|would)\s+you\s+)?(delete|remove|drop|erase|purge|wipe|get\s+rid\s+of)\b"
                        r"(?![^.?!]*\b(filters?|charts?|notes?|steps?|selections?|plans?|fix(es)?|rules?|sort(ing)?)\b)", re.I)
# A cell edit names its rows by number; a change by rule ("make these empty", "fix the typo in <a value>") is a
# cleaning command, which has no limit on how many cells it changes.
ROW_NAMED = re.compile(r"\brows?\s*(#|no\.?|number)?\s*\d", re.I)
# What a cell edit can't do to a numbered row: set it aside, bring it back, delete it. Code does those.
ROW_OP = re.compile(r"\b(quarantin\w*|set\s+aside|restor\w*|bring\s+back|un-?quarantin\w*|delet\w*|remov\w*|drop)\b", re.I)
# New rows go through the cell edits, as in the grid: code has no `_row_id`s to give them.
ADD_ROW = re.compile(r"^\W*(please\s+)?((can|could|would)\s+you\s+)?(add|insert|append|create|enter)\s+"
                     r"(a\s+|an\s+|one\s+|another\s+|some\s+|\d+\s+|two\s+|three\s+|four\s+|five\s+|ten\s+)?"
                     r"(new\s+|blank\s+|empty\s+|more\s+|extra\s+)?(rows?|records?|entr(y|ies)|lines?)\b", re.I)
# "Sort by <a column>": the grid's view, as a click on its header would do (the file keeps its row order).
SORT_ASK = re.compile(r"^\W*(please\s+)?((can|could|would)\s+you\s+)?(sort|order|arrange)\s+"
                      r"((it|them|everything|the\s+(rows|data|table|file|grid|records|csv))\s+)?by\s+(?P<column>.+?)"
                      r"(\s*[,(]?\s*(?:in\s+)?(?P<dir>asc\w*|desc\w*|reverse\w*|high\w*\s+(to\s+\w+|first)|low\w*\s+(to\s+\w+|first)|"
                      r"largest\s+first|smallest\s+first|biggest\s+first|a\s*(-|to)\s*z|z\s*(-|to)\s*a)(\s+order)?\)?)?\W*$", re.I)
UNSORT = re.compile(r"^\W*(please\s+)?(clear|remove|reset|undo|turn\s+off)\s+(the\s+)?sort(ing)?\W*$|^\W*unsort\b", re.I)
# A message that starts by telling Sherlock to change the data is a cleaning command, whatever the router said:
# live (Nemotron, 2026-10-27), "make <a column> a whole number by rounding" and "fill the missing <a column> values
# with <a value>" went to ask_data, and "add <a name> = <a column> + <another>" to ask_code. Not a request for a
# chart or a list ("make a chart of …"), and not a question.
COMMAND_VERBS = (r"make|set|change|convert|turn|replace|rename|trim|strip|fill|impute|standardi[sz]e|normali[sz]e|fix|"
                 r"correct|round|cast|split|merge|combine|upper-?case|lower-?case|title-?case|capitali[sz]e|reformat|format|"
                 r"parse|recode|map|swap|quarantine|set\s+aside|clear|blank\s+out|empty|collapse|truncate|move|reorder|"
                 r"rearrange|restore|un-?quarantine|bring\s+back|de-?dupe|de-?duplicate")
# Live (2026-10-27), "could you add a <name> column = …" went to ask_data and "collapse the repeated spaces in <a column>"
# to ask_data: the column may carry its name before the word, and "collapse" is a change like the others.
COMMAND = re.compile(
    r"^\W*(please\s+)?((can|could|would)\s+you\s+)?(" + COMMAND_VERBS + r"|"
    r"add\s+(a\s+|an\s+)?(new\s+)?(computed\s+)?([\w.]+\s+)?column|add\s+[\w.]+(?=\s*=)|create\s+(a\s+|an\s+)?(new\s+)?column)\b"
    r"(?![^.?!]*\b(charts?|plots?|graphs?|histograms?|lists?|summary|report|notebook)\b)", re.I)
# The same request, worded without a leading verb. Live (Nemotron, 2026-10-27, samples/eval/commands.yaml), these went
# to ask_data and were answered as questions: a wish ("I want the empty <a column> cells filled with <a value>", "I want
# the <records> with no <a column> gone", "I want <a column> as integers"), a problem and its fix ("the <a column> has
# gaps, fill them with <a value>", "the <records> shouldn't be in this file, get rid of them") and a bare arrow ("<a column>
# → 2dp"). Not a question, a chart or a list.
COMMAND_WORDED = re.compile(
    r"^(?![^.?!]*\b(charts?|plots?|graphs?|histograms?|lists?|summary|report|notebook)\b)(?:"
    r"\W*(i\s+(want|need|would\s+like)|i'?d\s+like)\s+(to\s+(" + COMMAND_VERBS + r"|delete|remove|drop|get\s+rid\s+of)\b|(?!to\s)"
    r"(?=[^?!]*\b(filled|rounded|replaced|trimmed|removed|deleted|dropped|converted|fixed|cleaned|corrected|gone|capitals|small\s+letters|"
    r"upper\s*case|lower\s*case|integers?|whole\s+numbers?|new\s+column)\b))"
    r"|(?!\W*(which|what|how|why|who|when|where|is|are|does|do|did)\b)[^?!]*[,;]\s*(and\s+|then\s+|so\s+)?(please\s+)?"
    r"(" + COMMAND_VERBS + r"|add|delete|remove|drop|get\s+rid\s+of)\s+(it|them|those|these|that|this)\b"
    r"|\W*[\w. ]{1,40}\s*(→|->)\s*\S[^?]*$|\W*new\s+column\s+[\w.]+\s*=)", re.I)
# Analysis a single query can't do well: a fit, clusters, fuzzy matching. Live, "the slope of <a measure> against
# <another>" went to ask_data, whose query answered something else.
CODE_ASK = re.compile(r"\b(regress\w*|slope|trend\s*line|line\s+of\s+best\s+fit|best[- ]fit|clusters?|clustering|"
                      r"k-?means|fuzzy|principal\s+components?|pca)\b", re.I)
# With a plan open, a message about the plan's fixes changes the plan; any other change to the data is a command.
PLAN_WORDS = re.compile(r"^\W*also\b|\b(plan|fix(es)?|untick|tick|don'?t\s+touch|leave\s+[^.?!]*\balone|leave\s+out|put\s+back|"
                        r"skip|instead|worth\s+a\s+look|cosmetic)\b", re.I)
# Records that meet a numeric condition are a row list: live (ask eval), Nano sent "which <records> paid more than
# <an amount>?" to ask_data, which answered with a table, not the rows. Not when it asks for a number about them, or
# a ranking; a group ("which <a group column> has more than …") is checked against the resolved names.
ROW_LIST = re.compile(r"^\W*(which|who|list|show|find)\b(?![^.?!]*\b(how many|number of|average|mean|median|total|sum|"
                      r"rate|share|percent\w*|proportion|count)\b)[^.?!]*\b((more|less|fewer|\w+er)\s+than|"
                      r"over|under|above|below|at\s+(least|most))\s+\$?\d", re.I)
GROUP_NOUN = re.compile(r"^\W*(which|what)\s+(\w+)", re.I)
# "Why did <a group> <do something> more often?" asks what explains an outcome: live (ask eval), Nano sent it to
# ask_data, which gave one rate and no model. Not a question about what Sherlock did ("why did you …", the quarantine).
WHY_ASK = re.compile(r"^\W*why\b(?![^.?!]*\b(you|quarantin\w*|clean\w*|steps?|chang\w*|left out|dropp\w*|exclud\w*)\b)", re.I)
# A question about the future: there's no forecast recipe (PRD ML-11, P1), and the model never makes up a number.
FORECAST = re.compile(r"\b(forecast\w*|predict\w*|project\w*|extrapolat\w*)\b[^.?!]*\b(next|future|coming|upcoming|tomorrow|ahead)\b|"
                      r"\b(next|coming|upcoming)\s+(\d+\s+|few\s+)?(years?|months?|weeks?|quarters?|seasons?|decades?|days?)\b|\bin the future\b", re.I)


def names_group(question: str, resolved: dict, roles: dict) -> bool:
    """Whether "which <noun> …" asks about a group column ("which class has more than …"), not the records: the noun
    resolved to a column, or shares a stem with a category column's name."""
    m = GROUP_NOUN.match(question)
    if not m:
        return False
    noun = m.group(2).lower()
    if any(noun in t.lower().split() for t in resolved.get("columns") or {}):
        return True
    return any(role == "dimension" and (noun == c.lower() or stem_linked(noun, c)) for c, role in roles.items())


def sort_of(question: str, columns: list[str]) -> dict | None:
    """`{column, dir}` when the message asks to sort the grid by a column of this file (`column` None to clear the
    sort), else None: a name that isn't a column goes on to the router ("order the classes by average fare")."""
    if UNSORT.search(question):
        return {"column": None, "dir": "asc"}
    m = SORT_ASK.search(question)
    if not m:
        return None
    said = re.sub(r"^(the\s+)?|\s+(column|field)$", "", m.group("column").strip(), flags=re.I).strip(" \"'`")
    plain = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())  # noqa: E731
    column = next((c for c in columns if c.lower() == said.lower()), None) or \
        next((c for c in columns if plain(c) == plain(said)), None)
    if column is None:
        return None
    way = (m.group("dir") or "").lower()
    desc = way.startswith(("desc", "reverse", "high", "largest", "biggest")) or bool(re.match(r"z\s*(-|to)\s*a", way))
    return {"column": column, "dir": "desc" if desc else "asc"}


def swap(intents: list[str], old: tuple[str, ...], new: str) -> list[str]:
    """The intents with each of `old` replaced by `new`, each intent once."""
    return list(dict.fromkeys(new if i in old else i for i in intents))


def to_message(row: sqlite3.Row, db: sqlite3.Connection | None = None, current_version: int | None = None) -> dict:
    """A message in the TRD §4.9 `Message` shape (with its proposal when `db` is given)."""
    out = {
        "id": row["id"], "role": row["role"], "text": row["text"], "blocks": json.loads(row["blocks_json"]),
        "sources": json.loads(row["sources_json"]), "created_at": row["created_at"],
        "clarification_of": row["clarification_of"], "version": row["version"],
    }
    if row["clarification_json"]:
        out["clarification"] = json.loads(row["clarification_json"])
    if row["plan_json"]:
        out["plan"] = json.loads(row["plan_json"])
    focus = json.loads(row["focus_json"]) if row["focus_json"] else {}
    if focus.get("actions"):
        out["actions"] = [a for a in focus["actions"] if a.get("kind") not in ("pin", "add_to_flow", "open_widget", "undo_widget")]
    if row["proposal_id"] and db is not None:
        p = db.execute("SELECT * FROM proposals WHERE id = ?", (row["proposal_id"],)).fetchone()
        if p:
            out["proposal"] = acts.to_proposal(p)
    return out


def history_line(row: sqlite3.Row) -> str:
    """A history line's prefix: the version the message was written on, then its role ("[v5] assistant")."""
    return f"[v{row['version']}] {row['role']}" if row["version"] is not None else row["role"]


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
    def __init__(self, env: qx.Env, llm: LLMClient, dataset: sqlite3.Row, emit: Callable[[str, dict], None]) -> None:
        self.env, self.llm, self.dataset, self.emit = env, llm, dataset, emit
        self.db = env.db
        self.web = WebClient(env.settings)  # off (each web step says so in one line) without TAVILY_API_KEY
        self.started = time.monotonic()

    # --- persistence --------------------------------------------------------------------------

    def _save(self, mid: str, role: str, text: str, *, blocks=(), sources=(), context=None, focus=None,
              clarification=None, clarification_of=None, route=None, tokens=0, plan=None, proposal_id=None) -> dict:
        self.db.execute(
            "INSERT INTO messages (id, dataset_id, role, text, blocks_json, sources_json, context_json, focus_json, "
            "clarification_json, clarification_of, route_json, tokens_used, plan_json, proposal_id, created_at, version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (mid, self.dataset["id"], role, text, json.dumps(list(blocks), default=str), json.dumps(list(sources)),
             json.dumps(context) if context is not None else None, json.dumps(focus, default=str) if focus else None,
             json.dumps(clarification) if clarification else None, clarification_of,
             json.dumps(route) if route else None, tokens, json.dumps(plan) if plan else None, proposal_id, now_iso(),
             self.dataset["current_version"]),
        )
        return to_message(self.db.execute("SELECT * FROM messages WHERE id = ?", (mid,)).fetchone(), self.db)

    def _history(self) -> tuple[list[sqlite3.Row], dict | None]:
        rows = self.db.execute(
            "SELECT * FROM messages WHERE dataset_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
            (self.dataset["id"], HISTORY),
        ).fetchall()[::-1]
        focus = next((json.loads(r["focus_json"]) for r in reversed(rows) if r["role"] == "assistant" and r["focus_json"]), None)
        if focus:  # a clarification's focus carries the answer's before it
            focus = {k: v for k, v in focus.items() if k != "clarify"}
        return rows, focus

    # --- context ------------------------------------------------------------------------------

    def _scope(self, context: dict, types: dict[str, str]) -> Scope:
        scope = Scope()
        words = []
        if context.get("selection_id"):
            scope.selection_id = context["selection_id"]
            scope.selection = qx.selection_sql(self.db, self.dataset["id"], context["selection_id"])
            n = self.db.execute("SELECT label FROM selections WHERE id = ?", (context["selection_id"],)).fetchone()
            count = qx.selection_rows(self.env, self.dataset, context["selection_id"])  # on this version
            words.append(f"the selection {n['label'] or ''} ({count} rows)".replace("  ", " "))
        if words:
            scope.words = " and ".join(words)
        return scope

    def _context(self, card: dict, scope: Scope, history: list[sqlite3.Row], focus: dict | None, resolved: dict | None,
                 context: dict) -> str:
        # The scope's words carry a selection's label, which is the user's: fenced.
        parts = [card_summary(card), "Rows in scope ({{rows}} already applies this):\n" + fence(scope.words)]
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
        notes = aw.notes_context(self.db, self.dataset["id"], [c["name"] for c in card["columns"]])
        if notes:  # what the columns mean, from a data dictionary the user linked or the web (PRD LOAD-7, TRD §8.2)
            parts.append("What some columns mean (from a data dictionary or the web, not from the data):\n" + fence(notes))
        summary = self.db.execute("SELECT summary FROM thread_summaries WHERE dataset_id = ?", (self.dataset["id"],)).fetchone()
        if summary:
            parts.append("Earlier in this conversation (a summary):\n" + fence(summary["summary"]))
        # Each line says the version it was written on, so an answer from before an edit reads as older.
        recent = [f"{history_line(r)}: {r['text'][:300]}" for r in history if r["text"]]
        if recent:
            parts.append("Recent messages:\n" + fence("\n".join(recent)))
        return "\n\n".join(parts)

    # --- the loop -----------------------------------------------------------------------------

    def run(self, text: str, context: dict, clarification_of: str | None = None, choice: str | None = None) -> dict:
        dataset = self.dataset
        history, focus = self._history()
        user = self._save(new_id("msg"), "user", choice or text, context=context, clarification_of=clarification_of)
        mid = new_id("msg")
        # The 90 s budget is the scope's deadline, so a model call can't run past it (TRD §3.5, §13).
        scope = CallScope(user_id=dataset["user_id"], dataset_id=dataset["id"], message_id=mid,
                          on_wait=lambda t: self.emit("status", {"text": t}), deadline=self.started + WALL_S)
        question = text
        chosen = None  # what the picked option of a code-built clarification stands for
        # "What happened around <period>?" (docs/plans/tavily.md §3.6): a press of the offer saved on that message.
        pressed = self._period_offer(clarification_of, choice or text) if clarification_of else None
        if clarification_of and not pressed:
            asked = self.db.execute("SELECT * FROM messages WHERE id = ? AND dataset_id = ?", (clarification_of, dataset["id"])).fetchone()
            original = self.db.execute(
                "SELECT text FROM messages WHERE dataset_id = ? AND role = 'user' AND created_at <= ? AND id != ? "
                "ORDER BY created_at DESC, id DESC LIMIT 1", (dataset["id"], asked["created_at"] if asked else now_iso(), user["id"]),
            ).fetchone() if asked else None
            clar = (json.loads(asked["focus_json"]) if asked and asked["focus_json"] else {}).get("clarify") or {}
            picked = choice or text
            means = clar.get("means", {}).get(picked)
            chosen = {"name": clar.get("name") or picked, **means} if means else None
            said = f"by “{clar['name']}” I mean {picked}" if means and clar.get("name") else picked
            question = f"{original['text']}\n(Clarified: {said})" if original else picked

        try:
            if pressed:
                return self._period(mid, *pressed, context, scope)
            return self._answer(mid, question, context, scope, history, focus, clarified=bool(clarification_of), chosen=chosen)
        except (LLMUnavailable, BudgetExceeded) as exc:
            self.emit("error", {"code": exc.code, "message": exc.message})
            generic = type(exc) is LLMUnavailable  # a refused request or a deadline says so in its own words
            msg = "The model service is unavailable. Your data is safe; try again in a minute." if generic else exc.message
            block = text_block([{"type": "text", "text": msg}])
            out = self._save(mid, "assistant", msg, blocks=[block], tokens=scope.message_tokens[0])
            self.emit("message", out)
            return out

    def _answer(self, mid: str, question: str, context: dict, scope: CallScope, history, focus, clarified: bool,
                chosen: dict | None = None) -> dict:
        dataset = self.dataset
        self.emit("status", {"text": "Thinking…"})
        card = profile_service.get_or_build(self.env.settings, self.db, self.env.cache, dataset)
        types = qx.user_types(self.env, dataset, dataset["current_version"])
        columns = list(types)
        rows_scope = self._scope(context, types)
        base_context = self._context(card, rows_scope, history, focus, None, context)

        tools = TOOLS + (PLAN_TOOLS if context.get("plan_id") else ())
        if acts.EXPORT.search(question):
            return self._export(mid, question, context, scope)
        if aw.DICTIONARY_ASK.search(question) and aw.typed_url(question):
            return self._dictionary(mid, question, context, scope, columns)
        if FORECAST.search(question):
            return self._forecast(mid, question, context, card)
        sort = sort_of(question, columns)
        if sort is not None:
            return self._sort(mid, question, context, sort)
        route = self._route(question, base_context, scope, tools)
        clar = checked_clarification(route)
        if route.ambiguous and clar and not clarified:
            self.emit("clarification", clar)
            out = self._save(mid, "assistant", clar["question"], clarification=clar, context=context,
                             route=route.model_dump(), tokens=scope.message_tokens[0])
            self.emit("message", out)
            return out

        resolved = resolve(self.db, dataset["id"], [e.model_dump() for e in route.entities], columns)
        drop_counts(resolved, question)
        if chosen:
            choose(resolved, chosen)
        ctx_text = self._context(card, rows_scope, history, focus, resolved, context)
        kit = Toolkit(self.env, self.llm, scope, dataset, ctx_text, rows_scope, example=example_question(card),
                      resolved=resolved, types=types, roles={c["name"]: c["role"] for c in card["columns"]})
        asking: Clarify | None = None  # a code-built clarification, asked when no other step answers
        blocks, sources, results, actions, notes, streamed, computed = [], [], [], [], [], [], []
        focus_out = {"question": question, "intents": list(route.intents), "selection_id": rows_scope.selection_id}

        intents = list(dict.fromkeys(route.intents[:2]))
        if "ask_stats" in intents and not STATS_WORDS.search(question):
            intents = list(dict.fromkeys("ask_data" if i == "ask_stats" else i for i in intents))
        # Outside-world questions the router took for the file's: a meaning of nothing the file has ("what is
        # <a term>?") or that asks no meaning, or a history with no word about changes, goes to the web (live).
        if WEB_ASK.search(question) and "web_context" not in intents:
            intents = swap(intents, ("ask_history", "ask_meaning"), "web_context")
            if "web_context" not in intents:
                intents = swap(intents, (intents[0],), "web_context")
        if "ask_meaning" in intents and not (insight.names_a_column(question, resolved, columns) and MEANING_WORDS.search(question)):
            intents = swap(intents, ("ask_meaning",), "web_context")
        if "ask_history" in intents and not HISTORY_WORDS.search(question):
            intents = swap(intents, ("ask_history",), "web_context")
        if HOW_TO.search(question):
            intents = swap(intents, ("ask_history", "ask_model"), "app_help")
        if WHY_ASK.search(question):
            intents = swap(intents, ("ask_data", "find_rows"), "ask_why")
        if ROW_LIST.search(question) and not RANKING.search(question) and not names_group(question, resolved, kit.roles):
            intents = swap(intents, ("ask_data",), "find_rows")
        if QUARANTINE_ASK.search(question):
            intents = swap(intents, ("ask_data", "find_rows", "ask_why", "ask_stats", "ask_model"), "ask_history")
        if RANKING.search(question):
            intents = swap(intents, ("find_rows",), "ask_data")
        command = bool(COMMAND.search(question) or COMMAND_WORDED.search(question))
        analysis_only = bool(CODE_ASK.search(question) and not command)
        if analysis_only:  # live, "group the <records> into clusters by <a> and <b>" also ran ask_why and its model card
            intents = ["ask_code"]
        if command and not HOW_TO.search(question):
            plan_change = context.get("plan_id") and PLAN_WORDS.search(question)
            numbered = ROW_NAMED.search(question) and not ROW_OP.search(question)
            target = "edit_plan" if plan_change else "edit_cells" if numbered else "clean_step"
            intents = [target]
        elif context.get("plan_id") and "clean_step" in intents and PLAN_WORDS.search(question):
            intents = swap(intents, ("clean_step",), "edit_plan")
        elif context.get("plan_id") and "edit_plan" in intents and not PLAN_WORDS.search(question):
            intents = swap(intents, ("edit_plan",), "clean_step")
        adding = bool(ADD_ROW.search(question)) and not HOW_TO.search(question)
        if adding:
            intents = ["edit_cells"]
        elif "edit_cells" in intents and not (ROW_NAMED.search(question) and not ROW_OP.search(question)):
            intents = swap(intents, ("edit_cells",), "clean_step")
        if WHAT_IF.search(question):
            intents = swap(intents, ("clean_step", "edit_cells", "clean_selection"), "ask_data")
        deleting = bool(DELETE_ASK.search(question))
        if deleting:
            intents = ["clean_step"]
        steps = [(i, question) for i in intents]
        if route.multi_step and not deleting and not adding and not analysis_only:
            steps = self._plan(question, ctx_text, scope, tools) or steps
        plan = [{"text": f"{STEP_LABELS.get(i, i)}: {q}" if q != question else STEP_LABELS.get(i, i), "status": "pending"}
                for i, q in steps] if len(steps) > 1 else None
        if plan:
            self.emit("plan", {"steps": plan})
        proposal = None
        for n, (intent, q) in enumerate(steps, 1):  # noqa: B007 - `n` also counts the steps a command defers
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
                if intent in ("ask_data", "find_rows", "ask_code"):
                    self.emit("status", {"text": {"ask_data": "Running a query", "find_rows": "Finding rows",
                                                  "ask_code": "Working it out in code"}[intent]})
                    rid = f"r{len(results) + len(computed) + 1}"
                    if intent == "ask_code":
                        res = analysis.ask_code(kit, q, rid)
                    elif intent == "find_rows":
                        res = kit.find_rows(q, rid, columns)
                    else:
                        try:
                            res = kit.ask_data(q, rid)
                        except (CantAnswer, StructuredOutputError) as exc:
                            # SQL couldn't express it (not "no column records it"): pandas gets one try.
                            if isinstance(exc, Clarify) or not (isinstance(exc, StructuredOutputError) or getattr(exc, "sql_failed", False)):
                                raise
                            self.emit("status", {"text": "Working it out in code"})
                            res = analysis.ask_code(kit, q, rid)
                    results.append(res)
                    streamed.append(table_block(res))
                    self.emit("block", streamed[-1])  # the first block, before the prose is written
                    label = f"Query ({res.id})" + (f", reading {res.extra['reading']}" if res.extra.get("reading") else "")
                    if res.extra.get("code"):
                        label = f"Code ({res.id})" + (f", reading {res.extra['reading']}" if res.extra.get("reading") else "")
                        sources.append({"kind": "code", "code": res.extra["code"], "label": label, "result": res.id})
                    else:
                        sources.append({"kind": "sql", "sql": res.sql, "label": label, "result": res.id})
                    if res.selection_id:
                        actions.append({"kind": "open_rows", "selection_id": res.selection_id})
                elif intent == "ask_history":
                    if QUARANTINE_ASK.search(q):  # how many rows are quarantined and why, counted in code
                        reply = insight.quarantined(kit, f"r{len(results) + len(computed) + 1}")
                        blocks += reply.blocks
                        sources += reply.sources
                        if not (reply.focus or {}).get("quarantined"):
                            continue  # none are quarantined, so no step set them: the steps would be unrelated text
                    vrow = qx.version_row(self.db, dataset["id"], dataset["current_version"])
                    found = ask_history(self.db, dataset["id"], q, json.loads(vrow["effective_step_ids_json"]))
                    if not found:
                        if QUARANTINE_ASK.search(q):
                            continue
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
                elif intent == "edit_plan":
                    self.emit("status", {"text": "Changing the plan"})
                    summary = acts.edit_plan(kit, q, context)
                    blocks.append(text_block([{"type": "text", "text": summary}]))  # the panel follows plan.updated
                elif intent == "clean_step":
                    if proposal is not None:
                        raise CantAnswer("One change at a time: run or cancel the card above first.")
                    proposal = commands.propose(kit, q, context, types, lambda t: self.emit("status", {"text": t}))
                    later = [s for _, s in steps[n:]]
                    if later:  # the rest of the message runs on the changed data, once the user presses OK
                        proposal = commands.then(self.db, proposal, later, question, n)
                    self.emit("proposal", proposal)
                    blocks.append(text_block([{"type": "text", "text": f"{proposal['summary']}. Nothing has changed yet: "
                                               "read the code, then press OK to run it on the file, or Cancel."}]))
                    for warning in proposal.get("warnings") or []:  # said by code
                        blocks.append(text_block([{"type": "text", "text": warning}]))
                    if later:
                        blocks.append(text_block([{"type": "text", "text": "The rest of your message runs on the changed "
                                                   "data once you press OK."}]))
                        break
                elif intent in ("edit_cells", "clean_selection"):
                    if proposal is not None:
                        raise CantAnswer("One change at a time: approve or reject the proposal above first.")
                    self.emit("status", {"text": "Working out the change"})
                    proposal = (acts.propose_edits(kit, q, context, types) if intent == "edit_cells"
                                else acts.propose_clean(self.env, dataset, context, mid))
                    self.emit("proposal", proposal)
                    blocks.append(text_block([{"type": "text", "text": "Nothing has changed yet. Approve to apply this, "
                                               "or reject it." if intent == "edit_cells" else
                                               "Approve to start Clean with AI; each fix it makes is a step you can undo."}]))
                    for warning in proposal.get("warnings") or []:  # a value outside its column's range, said by code
                        blocks.append(text_block([{"type": "text", "text": warning}]))
                else:
                    raise CantAnswer(NOT_YET.get(intent, "I can't do that yet."))
            except Clarify as exc:
                if asking is None and not clarified and len(exc.options) >= 2:
                    asking = exc
                elif str(exc) not in notes:
                    notes.append(str(exc))
            except CantAnswer as exc:
                if str(exc) not in notes:
                    notes.append(str(exc))
            except StructuredOutputError:
                notes.append("I couldn't turn that into a query. Try naming the columns" +
                             (f", e.g. “{kit.example}”." if kit.example else "."))
            except DeadlineExceeded:
                notes.append("I stopped early to stay within this answer's budget.")
                break  # what the earlier steps found is still composed
            except ApiError as exc:
                if exc.code in ("llm_unavailable", "budget_exceeded"):
                    raise
                notes.append(exc.message)
            finally:  # also after an insight step's `continue`
                if plan:
                    ok = (len(blocks), len(results)) != before[:2] and len(notes) == before[2]
                    plan[n - 1]["status"] = "done" if ok else "failed"
                    self.emit("plan.step", {"index": n - 1, "status": plan[n - 1]["status"]})

        if asking is not None:
            if not (blocks or results or notes or proposal):
                return self._ask(mid, asking, route, context, scope, focus, plan)
            notes.append(str(asking))
        if results:
            self.emit("status", {"text": "Writing the answer"})
            known = {c["name"]: [v["value"] for v in c.get("top_values") or []] for c in card["columns"]}
            composed, by_model = compose(self.llm, scope, question, results, columns, dataset["current_version"],
                                         rows_scope.selection_id, known)
            by_id = {r.id: r for r in results}
            # A model card's numbers have no query to pin: shown as a table, never a pinnable chart.
            composed = [table_block(by_id[b["result"]]) if b["type"] == "chart" and b.get("result") in computed else b
                        for b in composed]
            # Of a model card's tables, show only those the prose cites; the fallback (no prose) shows them all.
            cited = {r.get("key", "").split(":")[0] for b in composed if b["type"] == "text"
                     for para in b["body"]["blocks"] for r in para["runs"] if r["type"] == "chip"}
            if by_model:
                composed = [b for b in composed
                            if not (b["type"] == "table" and b.get("result") in computed and b["result"] not in cited)]
            blocks = composed + blocks
        if results:
            queried = [r for r in results if r.id not in computed]
            if queried:
                focus_out.update({"sql": queried[0].template, "columns": [c["name"] for c in queried[0].columns]})
            focus_out["result_ids"] = [r.id for r in results]
        if notes and not blocks and any(n in NOT_YET.values() for n in notes):
            notes.append(self._suggestion(card))  # ASK-8: say what is answerable instead
        if results and "web_context" in [i for i, _ in steps] and any(b.get("labeled") == "web" for b in blocks):
            notes.append(aw.SIDE_BY_SIDE)  # a data step's chips beside a web step's text: never compared (TRD §8.2)
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
        if self.web.enabled:  # a dated answer with a clear jump offers "What happened around <period>?" (tavily.md §3.6)
            button = next((o for r in results if r.id not in computed and not r.extra.get("code")
                           for o in [period.offer(r)] if o), None)
            if button:
                actions.append(button)
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

    def _ask(self, mid: str, asking: Clarify, route: Route, context: dict, scope: CallScope, focus: dict | None,
             plan: list | None) -> dict:
        """A clarification built in code: its buttons, and in the focus what each one stands for,
        so the choice resumes with the name resolved. The focus keeps the previous answer's, for follow-ups."""
        clar = asking.clarification()
        self.emit("clarification", clar)
        kept = {k: v for k, v in (focus or {}).items() if k != "actions"}
        out = self._save(mid, "assistant", clar["question"], clarification=clar, context=context,
                         focus={**kept, "clarify": {"name": asking.name, "means": asking.means}},
                         route=route.model_dump(), tokens=scope.message_tokens[0], plan={"steps": plan} if plan else None)
        self.emit("message", out)
        return out

    def _period_offer(self, message_id: str, label: str) -> tuple[dict, dict] | None:
        """(the offer, the message's focus) when `label` is the text of an "ask_period" button saved on that
        assistant message. The period comes from the saved offer, never from what the request says."""
        row = self.db.execute("SELECT focus_json FROM messages WHERE id = ? AND dataset_id = ? AND role = 'assistant'",
                              (message_id, self.dataset["id"])).fetchone()
        focus = json.loads(row["focus_json"]) if row and row["focus_json"] else {}
        offer = next((a for a in focus.get("actions") or [] if a.get("kind") == "ask_period" and a.get("label") == label), None)
        return (offer, focus) if offer else None

    def _period(self, mid: str, offer: dict, asked: dict, context: dict, scope: CallScope) -> dict:
        """The press of "What happened around <period>?": one dated news search (`period.period_context`),
        without a routing call. A failure is one line, as for any web answer. The focus stays the data answer's,
        so a follow-up still continues that question."""
        self.emit("status", {"text": "Searching the news for that period"})
        card = profile_service.get_or_build(self.env.settings, self.db, self.env.cache, self.dataset)
        kit = Toolkit(self.env, self.llm, scope, self.dataset, "", Scope())
        question = asked.get("question") or offer["label"]
        try:
            reply = period.period_context(kit, self.web, question, offer["measure"], [c["name"] for c in card["columns"]],
                                          offer["start_date"], offer["end_date"])
            blocks, sources, web_focus = reply.blocks, reply.sources, reply.focus
        except CantAnswer as exc:
            blocks, sources, web_focus = [text_block([{"type": "text", "text": str(exc)}])], [], {}
        for b in blocks:
            self.emit("block", b)
        if sources:
            self.emit("sources", {"sources": sources})
        text = " ".join(runs_text(p["runs"]) for b in blocks if b["type"] == "text" for p in b["body"]["blocks"]).strip()
        focus = {**{k: v for k, v in asked.items() if k not in ("actions", "clarify")}, **web_focus}
        out = self._save(mid, "assistant", text, blocks=blocks, sources=sources, context=context, focus=focus,
                         tokens=scope.message_tokens[0])
        self.emit("message", out)
        return out

    def _export(self, mid: str, question: str, context: dict, scope: CallScope) -> dict:
        """"Export a notebook" (App Flow §17.1): the dialog, with the options the wording asks for."""
        options = acts.export_options(question)
        said = {"include_data": "without the data", "include_runs": "without the analyses"}
        extra = [said[k] for k in options]
        text = "Here's the notebook export" + (f", {' and '.join(extra)}" if extra else "") + \
               ". Check the options and press Export; it downloads when it's ready."
        out = self._save(mid, "assistant", text, blocks=[text_block([{"type": "text", "text": text}])], context=context,
                         focus={"question": question, "intents": ["open_export"],
                                "actions": [{"kind": "open_export", "options": options}]})
        self.emit("message", out)
        return out

    def _sort(self, mid: str, question: str, context: dict, sort: dict) -> dict:
        """"Sort by <a column>" (`SORT_ASK`), without a model call: the grid sorts its view, as a click on the header
        does. The file's rows keep their order, so answers, the export and the notebook don't change."""
        if sort["column"] is None:
            text = "The grid is back in row order."
        else:
            way = "largest first" if sort["dir"] == "desc" else "smallest first"
            text = (f"The grid is sorted by {sort['column']}, {way}. Sorting changes the view, not the file; click the "
                    "column's header to change it.")
        out = self._save(mid, "assistant", text, blocks=[text_block([{"type": "text", "text": text}])], context=context,
                         focus={"question": question, "intents": ["sort_grid"], "actions": [{"kind": "sort_grid", **sort}]})
        self.emit("message", out)
        return out

    def _forecast(self, mid: str, question: str, context: dict, card: dict) -> dict:
        """A question about the future (`FORECAST`), answered without a model call: there's no forecast recipe
        (PRD ML-11, P1), and a number nobody computed is never given. It says whether the file has a time
        column to show the trend so far, and offers the closest question this file can answer (ASK-8)."""
        times = [c["name"] for c in card["columns"] if c["role"] == "time" or c["type"] in ("date", "datetime")]
        if times:
            text = (f"I can't forecast: Sherlock has no forecasting model yet, and I only give numbers from queries "
                    f"that ran on the rows you have. I can show how it changed over time so far, by {times[0]}.")
        else:
            example = example_question(card)
            text = ("I can't forecast that: this file has no date or time column, so there's no trend over time to "
                    "extend, and I only give numbers from queries that ran on the rows you have."
                    + (f" I can describe the data as it is, for example “{example}”." if example else ""))
        out = self._save(mid, "assistant", text, blocks=[text_block([{"type": "text", "text": text}])], context=context,
                         focus={"question": question, "intents": ["forecast"]})
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
        return steps[:5] if len(steps) >= 2 else None

    def _summarize(self, scope: CallScope) -> None:
        """Fold older messages into the running summary, ten at a time, with `small` (TRD §8.1 step 1).
        Best effort: a failure keeps the old summary."""
        row = self.db.execute("SELECT * FROM thread_summaries WHERE dataset_id = ?", (self.dataset["id"],)).fetchone()
        after = row["up_to_message_id"] if row else ""
        older = self.db.execute(
            "SELECT id, role, text, version FROM messages WHERE dataset_id = ? AND id > ? ORDER BY created_at, id",
            (self.dataset["id"], after)).fetchall()[:-HISTORY]  # the latest six stay in the context as they are
        if len(older) < SUMMARY_EVERY:
            return
        lines = "\n".join(f"{history_line(m)}: {m['text'][:300]}" for m in older)
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
                  "ask_meaning": "Looking at the column", "app_help": "Looking in the help",
                  "web_context": "Searching the web"}[intent]
        self.emit("status", {"text": status})
        if intent == "ask_stats":
            return insight.ask_stats(kit, question, resolved, card, rid)
        if intent == "ask_why":
            left = WALL_S - (time.monotonic() - self.started) - 15
            return insight.ask_why(kit, question, resolved, card, rid, wait_s=max(0.0, min(insight.WAIT_S, left)),
                                   status=lambda t: self.emit("status", {"text": t}))
        if intent == "ask_model":
            return insight.ask_model(kit, question, resolved, context, focus, rid)
        if intent == "ask_meaning":
            return insight.ask_meaning(kit, question, resolved, card, rid, web=self.web)
        if intent == "web_context":
            return aw.web_context(kit, self.web, question, [c["name"] for c in card["columns"]])
        return insight.app_help(question)

    def _dictionary(self, mid: str, question: str, context: dict, scope: CallScope, columns: list[str]) -> dict:
        """"Use the codebook at <url>" (PRD LOAD-7, TRD §7.1.1): read the data dictionary at the URL the user
        typed, without a routing call, and say which columns it describes."""
        self.emit("status", {"text": "Reading the data dictionary"})
        url = aw.typed_url(question)
        got = aw.read_dictionary(self.llm, scope, self.web, self.db, self.dataset["id"], url, columns)
        if got["notes"]:
            named = [n["column"] for n in got["notes"]]
            text = (f"I read the data dictionary: it describes {', '.join(named[:12])}"
                    + (" and more" if len(named) > 12 else "") + ". Hover a column's header in the CSV tab to see its note.")
            sources = [{"kind": "web", "url": u, "title": t, "label": f"{t} ({aw._domain(u)}), retrieved {d}: from the web, not "
                        "from your data"} for u, t, d in dict.fromkeys((n["source_url"], n["source_title"] or aw._domain(n["source_url"]),
                                                                          n["retrieved_at"]) for n in got["notes"])]
        else:
            text, sources = got["note"], []
        out = self._save(mid, "assistant", text, blocks=[text_block([{"type": "text", "text": text}])], sources=sources,
                         context=context, focus={"question": question, "intents": ["dictionary"]}, tokens=scope.message_tokens[0])
        self.emit("message", out)
        return out

    @staticmethod
    def _suggestion(card: dict) -> str:
        """The closest answerable kind of question, with this file's own columns."""
        example = example_question(card)
        if example:
            return f"Meanwhile I can break the data down, for example “{example}”."
        return "Meanwhile I can answer questions about the data, find rows, or explain what changed."

    def _route(self, question: str, context: str, scope: CallScope, tools=TOOLS) -> Route:
        intents = "\n".join(f"- {prompts.INTENT_LINES[i]}" for i in tools)
        messages = [{"role": "system", "content": prompts.SYSTEM},
                    {"role": "user", "content": prompts.ROUTE.format(intents=intents, context=context, message=fence(question))}]
        try:
            return self.llm.structured("small", messages, Route, purpose="route", scope=scope, reasoning=False).value
        except StructuredOutputError:
            # TRD §3.5: the router's fallback treats the message as a single ask_data question.
            return Route(intents=["ask_data"], ambiguous=False, clarification=None, multi_step=False, entities=[])


def checked_clarification(route: Route) -> dict | None:
    """The router's clarification under the wording check: its question and options are the
    model's words shown as buttons. An option that fails is dropped; with fewer than two left, or a
    question that fails, there's no clarification and the message is answered as routed."""
    if not route.ambiguous or route.clarification is None:
        return None
    clar = route.clarification.model_dump()
    options = [o.strip() for o in clar["options"] if o.strip() and not wording_problem(o)]
    if wording_problem(clar["question"]) or len(options) < 2:
        return None
    return {"question": clar["question"], "options": options[:3]}


def choose(resolved: dict, chosen: dict) -> None:
    """Put the picked option of a code-built clarification into the message's names."""
    name = chosen["name"]
    if "column" in chosen:
        resolved["columns"][name] = chosen["column"]
    elif "value" in chosen:
        resolved["values"][name] = list(chosen["value"])
    elif "columns" in chosen:
        for c in chosen["columns"]:
            resolved["columns"][c] = c
    if name in resolved["unresolved"]:
        resolved["unresolved"].remove(name)
