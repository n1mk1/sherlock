"""Compose and verify (TRD §8.1 steps 6–7).

The model (`small`, schema `Answer`) picks the answer's shape and writes chip-based prose: every
number is a chip naming a result cell (`r1:0:2`, or `r1:total` for a row count), and text runs
can't contain digits. Code fills every value from the referenced cells, so the model never types a
number. The validator rejects a chip that names no cell, a label with digits, or a number answer
without its chip; after one repair the fallback is the raw results with their sources.
"""

import math
import re

from sherlock.agent.answerers import Result
from sherlock.llm.client import BudgetExceeded, CallScope, LLMClient, LLMUnavailable, StructuredOutputError, data_block
from sherlock.llm.schemas import Answer, ChipRun, LabelRun, TextRun
from sherlock.llm.text import has_digits

from sherlock.agent import prompts

CHIP = re.compile(r"^(r\d+):(?:(\d+):(\d+)|total)$")
PCT_NAME = re.compile(r"(rate|share|pct|percent|ratio|proportion|fraction)", re.I)
INLINE_ROWS = 20


def fmt_kind(value, column: str) -> str:
    if isinstance(value, bool) or value is None:
        return "text"
    if isinstance(value, (int, float)) and PCT_NAME.search(column or "") and 0 <= value <= 1:
        return "pct"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "num"
    return "text"


def fmt(value, kind: str) -> str:
    if value is None:
        return "—"
    if kind == "pct":
        return f"{value * 100:.1f}%"
    if kind == "int":
        return f"{value:,}"
    if kind == "num":
        v = float(value)
        if not math.isfinite(v):
            return str(v)
        if abs(v) >= 1000:
            return f"{v:,.0f}"
        if abs(v) >= 1:
            return f"{v:,.2f}"
        return f"{v:.3g}"
    return str(value)


def resolve_chip(ref: str, results: dict[str, Result]) -> tuple[object, str, str]:
    """(value, formatted, column) for a chip reference, or ValueError."""
    m = CHIP.match(ref.strip())
    if not m or m.group(1) not in results:
        raise ValueError(f"chip {ref!r} names no result")
    res = results[m.group(1)]
    if m.group(2) is None:
        total = res.total if res.total is not None else res.row_count
        return total, fmt(total, "int"), "rows"
    r, c = int(m.group(2)), int(m.group(3))
    if r >= len(res.rows) or c >= len(res.columns):
        raise ValueError(f"chip {ref!r} names a cell outside result {res.id} ({len(res.rows)} rows, {len(res.columns)} columns)")
    value = res.rows[r][c]
    column = res.columns[c]["name"]
    # A computed result (a model card) may say how each cell reads: its rows mix rates and counts.
    kind = res.extra.get("formats", {}).get(f"{r}:{c}") or fmt_kind(value, column)
    return value, fmt(value, kind), column


def label_text(ref: str, columns: list[str], values: set[str] | None = None) -> str:
    """The text a label shows. With `values`, a `value:` label must be one of them: it's shown as
    written, so a value the data doesn't have ("fare 512.33") could carry a number the model made up."""
    kind, _, rest = ref.partition(":")
    if kind == "column" and rest in columns:
        return rest
    if kind == "value":
        col, _, val = rest.partition(":")
        if col in columns and val:
            if values is not None and val not in values and f"{col}:{val}" not in values:
                raise ValueError(f"label {ref!r} is a value no result shows; use a chip for a number")
            return val
    raise ValueError(f"label {ref!r} names no column or value of this file")


def label_values(results: dict[str, Result], known: dict[str, list] | None = None) -> set[str]:
    """The values a `value:` label may show (Day 6 review F2): any cell of the answer's results, and
    `<column>:<value>` for the values the DataCard knows (its top values)."""
    out = {str(v) for res in results.values() for row in res.rows for v in row if v is not None}
    return out | {f"{col}:{v}" for col, vals in (known or {}).items() for v in vals if v is not None}


def to_runs(prose: list, results: dict[str, Result], columns: list[str], known: dict[str, list] | None = None) -> list[dict]:
    """Runs with every value filled in by code. A sentence that runs into the next gets its space,
    and prose that doesn't end a sentence gets its full stop. `known`: the DataCard's values by column."""
    runs = []
    values = label_values(results, known)
    for i, run in enumerate(prose):
        if isinstance(run, ChipRun):
            value, shown, _ = resolve_chip(run.chip, results)
            if runs and runs[-1]["type"] == "chip":
                runs.append({"type": "text", "text": ", "})  # two chips in a row read as a list
            runs.append({"type": "chip", "id": f"c{i}", "key": run.chip, "value": shown, "raw": value, "unverified": False})
        elif isinstance(run, LabelRun):
            runs.append({"type": "label", "ref": run.label, "text": label_text(run.label, columns, values)})
        elif isinstance(run, TextRun):
            text = run.text
            prev = runs[-1] if runs else None
            if prev and prev["type"] == "text" and prev["text"].rstrip().endswith((".", "!", "?")) and text[:1].isalnum():
                text = " " + text
            runs.append({"type": "text", "text": text})
    if runs and not (runs[-1]["type"] == "text" and runs[-1]["text"].rstrip().endswith((".", "!", "?", ":"))):
        runs.append({"type": "text", "text": "."})
    return runs


def runs_text(runs: list[dict]) -> str:
    return "".join(r.get("value") if r["type"] == "chip" else r.get("text", "") for r in runs).strip()


def text_block(runs: list[dict]) -> dict:
    return {"type": "text", "body": {"blocks": [{"type": "paragraph", "runs": runs}]}}


def table_block(res: Result) -> dict:
    return {"type": "table", "columns": res.columns, "rows": res.rows[:INLINE_ROWS],
            "total": res.total if res.total is not None else res.row_count, "selection_id": res.selection_id,
            "result": res.id}


def number_block(res: Result, r: int, c: int, label: str) -> dict:
    value = res.rows[r][c]
    kind = res.extra.get("formats", {}).get(f"{r}:{c}") or fmt_kind(value, res.columns[c]["name"])
    return {"type": "number", "value": value, "formatted": fmt(value, kind), "format": kind, "label": label,
            "result": res.id, "cell": [r, c]}


def chart_block(res: Result, view: str, version: int, selection_id: str | None) -> dict | None:
    """A chart of the first column against the first numeric column after it, as a pinnable spec."""
    if res.row_count < 2 or len(res.columns) < 2:
        return None
    numeric = [i for i, col in enumerate(res.columns[1:], 1)
               if any(isinstance(row[i], (int, float)) and not isinstance(row[i], bool) for row in res.rows)]
    if not numeric:
        return None
    x, y = res.columns[0]["name"], res.columns[numeric[0]]["name"]
    spec = {
        "scope": {"columns": {"x": x, "y": y, "agg": None, "series": None, "target": None, "features": None, "exclude": []},
                  "rows": {"predicate": None, "selection_id": selection_id, "inherit_global_filters": True}},
        "op": {"type": "sql", "sql": res.template},
        "view": {"type": view, "from": "result", "options": {"x": x, "y": y}},
    }
    data = {"version": version, "columns": res.columns, "rows": res.rows, "row_count": res.row_count,
            "truncated": res.truncated}
    return {"type": "chart", "spec": spec, "data": data, "result": res.id}


def fallback_blocks(results: list[Result], version: int) -> list[dict]:
    """The raw results with their sources (App Flow §18): a single value as a number, else a table."""
    blocks = []
    for res in results:
        if res.row_count == 1 and len(res.columns) == 1 and res.total is None:
            blocks.append(number_block(res, 0, 0, res.columns[0]["name"]))
        else:
            blocks.append(table_block(res))
    return blocks


def rows_found(res: Result) -> list[dict]:
    """A `find_rows` answer, written in code: the count as a chip, then the first rows."""
    total = res.total if res.total is not None else res.row_count
    runs = [{"type": "chip", "id": "c0", "key": f"{res.id}:total", "value": fmt(total, "int"), "raw": total, "unverified": False},
            {"type": "text", "text": " row matches." if total == 1 else " rows match."}]
    if total > INLINE_ROWS:
        runs.append({"type": "text", "text": " Here are the first ones; open them all in the CSV tab."})
    return [text_block(runs), table_block(res)]


def compose(llm: LLMClient, scope: CallScope, question: str, results: list[Result], columns: list[str],
            version: int, selection_id: str | None, known: dict[str, list] | None = None) -> tuple[list[dict], bool]:
    """(blocks, composed_by_model). Row lists from `find_rows` are composed in code. `known`: the
    DataCard's values by column, which value labels may name besides the results' cells."""
    if all(r.selection_id for r in results):
        return [b for r in results for b in rows_found(r)], False
    results = [r for r in results if not r.selection_id] + [r for r in results if r.selection_id]
    by_id = {r.id: r for r in results}

    def check(a: Answer) -> None:
        to_runs(a.prose, by_id, columns, known)  # raises on a chip or label that names nothing
        if not a.prose:
            raise ValueError("write one to three sentences of prose")
        if a.prose:
            # One text run of at least two words, so bare names ("class", "avg_fare") don't pass for a sentence.
            if not any(isinstance(r, TextRun) and sum(any(ch.isalpha() for ch in w) for w in r.text.split()) >= 2
                       for r in a.prose):
                raise ValueError("the prose needs a sentence in words around the chips, not only chips or names")
        if a.shape == "number":
            if not a.number:
                raise ValueError("shape number needs the chip of the value in `number`")
            resolve_chip(a.number, by_id)
            if a.label and has_digits(a.label):
                raise ValueError("the label may not contain digits")
        if a.shape == "chart" and not any(r.row_count >= 2 for r in results):
            raise ValueError("a chart needs a result with at least two rows; use number, table or text")

    messages = [{"role": "system", "content": prompts.SYSTEM},
                {"role": "user", "content": prompts.COMPOSE.format(
                    message=data_block(question), results="\n\n".join(r.for_prompt() for r in results))}]
    try:
        # `medium`, not `small`: live, Nano strung chips together without words (TRD §8.1 step 6).
        a = llm.structured("medium", messages, Answer, purpose="compose", scope=scope, validate=check).value
    except (StructuredOutputError, LLMUnavailable, BudgetExceeded):
        return fallback_blocks(results, version), False

    blocks = []
    runs = to_runs(a.prose, by_id, columns, known)
    if runs:
        blocks.append(text_block(runs))
    main = results[0]
    if a.shape == "number":
        m = CHIP.match(a.number.strip())
        res = by_id[m.group(1)]
        if m.group(2) is None:
            blocks.append({"type": "number", "value": res.total if res.total is not None else res.row_count,
                           "formatted": fmt(res.total if res.total is not None else res.row_count, "int"),
                           "format": "int", "label": a.label or "rows", "result": res.id, "cell": None})
        else:
            blocks.append(number_block(res, int(m.group(2)), int(m.group(3)), a.label or res.columns[int(m.group(3))]["name"]))
    elif a.shape == "chart":
        res = next(r for r in results if r.row_count >= 2)
        chart = chart_block(res, a.chart or "bar", version, selection_id)
        blocks.append(chart or table_block(res))
    else:  # table, or text: the rows behind the prose stay visible
        blocks.append(table_block(main))
    for extra in results[1:]:
        if not any(b.get("result") == extra.id for b in blocks):
            blocks.append(table_block(extra))
    return blocks, True
