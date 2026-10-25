"""Answerers for Implementation Plan D7.3 (TRD §8.2): `ask_stats`, `ask_why`, `ask_model`,
`ask_meaning` and `app_help`.

Every number is computed in code: a test's statistic and p-value with SciPy, a model's metrics from
its model card (themselves from executing the run's `repro.py`), a column's counts with a query.
The prose of `ask_stats`, `ask_why` and `ask_meaning` is written in code, with each number a chip
naming a cell of a result, so it is grounded by construction. `ask_model` hands the model card as
results to the composer, which cites their cells the same way. The only model-written text that
isn't a composed answer is `ask_meaning`'s general explanation, which has no digits and is labelled
as general knowledge, not from the data.
"""

import json
import math
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz
from scipy import stats

from sherlock.agent import prompts
from sherlock.agent.answerers import CantAnswer, Result, Toolkit
from sherlock.agent.compose import fmt, fmt_kind, table_block, text_block
from sherlock.config import REPO_ROOT
from sherlock.errors import ApiError
from sherlock.llm.client import BudgetExceeded, LLMUnavailable, StructuredOutputError, data_block
from sherlock.llm.schemas import Meaning, StatsDraft
from sherlock.rows.query import ident
from sherlock.widgets import service as ws

HELP_DIR = REPO_ROOT / "docs" / "help"
MAX_GROUPS = 20
NUMBER_DISTINCT = 10       # an int or float column with more distinct values is a number, else a category
SIGNIFICANT = 0.05
WAIT_S = 60.0              # how long ask_why waits for a run it started
WRONG = re.compile(r"\b(wrong|misclassif\w*|mistakes?|errors?|missed)\b", re.I)
ONE_ROW = re.compile(r"\b(row|passenger|record|customer)\s+#?\d+", re.I)
TYPE_WORDS = {"int": "whole-number", "float": "number", "category": "category", "bool": "yes/no", "text": "text",
              "date": "date", "datetime": "date-and-time", "id": "ID"}
ROLE_WORDS = {"dimension": "it groups rows", "measure": "a measure", "target_like": "it looks like an outcome",
              "id": "unique per row", "free_text": "free text", "time": "a time column", "empty": "it has no values"}


@dataclass
class Reply:
    blocks: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    actions: list = field(default_factory=list)
    results: list = field(default_factory=list)  # results for the composer (ask_model)
    focus: dict = field(default_factory=dict)


def chip(res: Result, r: int, c: int, shown: str | None = None) -> dict:
    value = res.rows[r][c]
    if shown is None:
        shown = fmt(value, fmt_kind(value, res.columns[c]["name"]))
    return {"type": "chip", "id": f"{res.id}-{r}-{c}", "key": f"{res.id}:{r}:{c}", "value": shown, "raw": value,
            "unverified": False}


def text(t: str) -> dict:
    return {"type": "text", "text": t}


def label(column: str) -> dict:
    return {"type": "label", "ref": f"column:{column}", "text": column}


def memory_result(rid: str, what: str, columns: list[tuple[str, str]], rows: list[list]) -> Result:
    """A result computed in code (a model card, a test), not by a query: `sql` says where it's from."""
    return Result(rid, what, "", [{"name": n, "type": t} for n, t in columns], rows, len(rows), extra={"kind": "computed"})


def mentioned(resolved: dict, columns: list[str]) -> list[str]:
    """The columns a message names, directly or through one of their values, in order."""
    names = list(resolved["columns"].values()) + [v[0] for v in resolved["values"].values()]
    return [n for n in dict.fromkeys(names) if n in columns]


def _p(p: float) -> str:
    return "<0.001" if p < 0.001 else f"{p:.3f}"


# --- ask_stats ------------------------------------------------------------------------------------

def _kind(col: dict) -> str:
    return "number" if col["type"] in ("int", "float") and (col.get("distinct") or 0) > NUMBER_DISTINCT else "category"


def ask_stats(kit: Toolkit, question: str, resolved: dict, card: dict, rid: str) -> Reply:
    """The test chosen by rules (TRD §8.2): two groups of a number → Welch's t and Mann-Whitney; more
    groups → Kruskal-Wallis; two categories → chi-square; two numbers → Pearson and Spearman. Each
    with an effect size."""
    cols = {c["name"]: c for c in card["columns"]}
    names = mentioned(resolved, list(cols))
    reading = ""
    if len(names) >= 2:
        a, b = names[0], names[1]
    else:
        def check(d: StatsDraft) -> None:
            if d.outcome not in cols or d.group not in cols:
                raise ValueError(f"outcome and group must be columns of this file: {', '.join(cols)}")
            if d.outcome == d.group:
                raise ValueError("pick two different columns")
        try:
            d = kit.llm.structured("medium", kit._messages(prompts.STATS.format(context=kit.context, message=data_block(question))),
                                   StatsDraft, purpose="stats", scope=kit.scope, validate=check).value
        except StructuredOutputError:
            raise CantAnswer("Which two columns should I compare? For example “is fare different between men and women?”.") from None
        a, b, reading = d.outcome, d.group, d.reading
    ka, kb = _kind(cols[a]), _kind(cols[b])
    if ka == "category" and kb == "number":
        a, b, ka, kb = b, a, kb, ka  # the number is the outcome
    where = f"{ident(a)} IS NOT NULL AND {ident(b)} IS NOT NULL"
    sql = f"SELECT {ident(a)} AS a, {ident(b)} AS b FROM t WHERE {kit.rows.rows()} AND {where}"
    with ws.connection(kit.env, kit.dataset, kit.dataset["current_version"]) as conn:
        df = conn.execute(sql).df()
    n = len(df)
    if n < 3:
        raise CantAnswer(f"There are too few rows with both {a} and {b} filled in to test.")
    extra = None
    if ka == "number" and kb == "number":
        x, y = pd.to_numeric(df["a"]), pd.to_numeric(df["b"])
        pr, sr = stats.pearsonr(x, y), stats.spearmanr(x, y)
        rows = [["Pearson correlation", float(pr.statistic), float(pr.pvalue), "r", float(pr.statistic), n],
                ["Spearman rank correlation", float(sr.statistic), float(sr.pvalue), "rho", float(sr.statistic), n]]
        effect_words, size = "a correlation", _size(abs(rows[0][4]), (0.1, 0.3, 0.5))
    elif ka == "number":
        groups = {k: pd.to_numeric(g) for k, g in df.groupby(df["b"].astype(str))["a"]}
        if len(groups) < 2:
            raise CantAnswer(f"{b} has a single value in these rows, so there's nothing to compare.")
        if len(groups) > MAX_GROUPS:
            raise CantAnswer(f"{b} has too many values to compare as groups; ask about a column with fewer categories.")
        if len(groups) == 2:
            g1, g2 = groups.values()
            t = stats.ttest_ind(g1, g2, equal_var=False)
            u = stats.mannwhitneyu(g1, g2)
            sd = math.sqrt((g1.var(ddof=1) + g2.var(ddof=1)) / 2) or 1.0
            d = float((g1.mean() - g2.mean()) / sd)
            rb = float(2 * u.statistic / (len(g1) * len(g2)) - 1)  # > 0 when g1 tends higher, as d is
            rows = [["Welch's t-test", float(t.statistic), float(t.pvalue), "Cohen's d", d, n],
                    ["Mann-Whitney U", float(u.statistic), float(u.pvalue), "rank-biserial r", rb, n]]
            effect_words, size = "Cohen's d", _size(abs(d), (0.2, 0.5, 0.8))
        else:
            h = stats.kruskal(*groups.values())
            eps = float(h.statistic / (n - 1))
            rows = [["Kruskal-Wallis", float(h.statistic), float(h.pvalue), "epsilon squared", eps, n]]
            effect_words, size = "epsilon squared", _size(eps, (0.01, 0.08, 0.26))
        extra = f"SELECT {ident(b)}, count(*) AS n, avg({ident(a)}) AS mean, median({ident(a)}) AS median FROM t " \
                f"WHERE {{{{rows}}}} AND {where} GROUP BY 1 ORDER BY 1"
    else:
        table = pd.crosstab(df["a"].astype(str), df["b"].astype(str))
        if min(table.shape) < 2:
            raise CantAnswer(f"One of {a} and {b} has a single value in these rows, so there's nothing to test.")
        if max(table.shape) > MAX_GROUPS:
            raise CantAnswer("One of those columns has too many values for a chi-square test.")
        chi2, p, _, _ = stats.chi2_contingency(table)
        v = float(math.sqrt(chi2 / (n * (min(table.shape) - 1))))
        rows = [["Chi-square test of independence", float(chi2), float(p), "Cramér's V", v, n]]
        effect_words, size = "Cramér's V", _size(v, (0.1, 0.3, 0.5))
        extra = f"SELECT {ident(b)}, {ident(a)}, count(*) AS n FROM t WHERE {{{{rows}}}} AND {where} GROUP BY 1, 2 ORDER BY 1, 2"
    res = memory_result(rid, f"{rows[0][0]} on the rows of: {sql}",
                        [("test", "VARCHAR"), ("statistic", "DOUBLE"), ("p_value", "DOUBLE"), ("effect", "VARCHAR"),
                         ("effect_size", "DOUBLE"), ("n", "BIGINT")], rows)
    p = rows[0][2]
    runs = [label(a), text(" and "), label(b), text(f": the {rows[0][0]} gives a p-value of "), chip(res, 0, 2, _p(p)),
            text(f", with {effect_words} of "), chip(res, 0, 4, f"{rows[0][4]:.2f}"), text(f" ({size}) on "), chip(res, 0, 5),
            text(" rows. ")]
    if p < SIGNIFICANT:
        runs.append(text("A pattern this strong is unlikely to be chance (below the usual significance threshold); "
                         "it's an association, not proof of a cause."))
    else:
        runs.append(text("That could well be chance: the test doesn't show a real difference at the usual threshold."))
    if len(rows) > 1:
        runs += [text(f" The {rows[1][0]} agrees with a p-value of " if (rows[1][2] < SIGNIFICANT) == (p < SIGNIFICANT)
                      else f" The {rows[1][0]} disagrees, with a p-value of "), chip(res, 1, 2, _p(rows[1][2])), text(".")]
    out = Reply(blocks=[text_block(runs), table_block(res)],
                sources=[{"kind": "sql", "sql": sql, "label": "The rows tested" + (f", reading {reading}" if reading else "")}])
    if extra:
        summary = kit._run(extra, f"{rid}g")
        out.blocks.append(table_block(summary))
        out.sources.append({"kind": "sql", "sql": summary.sql, "label": "The groups"})
    out.focus = {"columns": [a, b], "test": rows[0][0]}
    return out


def _size(v: float, cuts: tuple[float, float, float]) -> str:
    return "negligible" if v < cuts[0] else "small" if v < cuts[1] else "medium" if v < cuts[2] else "large"


# --- ask_why --------------------------------------------------------------------------------------

def ask_why(kit: Toolkit, question: str, resolved: dict, card: dict, filters: list[dict], rid: str,
            wait_s: float = WAIT_S, status=lambda _: None) -> Reply:
    """"What drives X?": the `driver_analysis` run for X on the chat's rows, cached when it exists,
    else started and waited for (up to a minute); then its verdict and strongest factors."""
    from sherlock.ml import registry
    from sherlock.ml import runner as ml

    targets = registry.targets(card)
    named = [c for c in mentioned(resolved, [c["name"] for c in card["columns"]]) if c in targets]
    target = named[0] if named else (targets[0] if targets else None)
    if target is None:
        raise CantAnswer("There's no column to explain in this file: it needs a yes/no, a category or a number.")
    req = ml.parse_request({"recipe": "driver_analysis", "filters": filters,
                            "scope": {"columns": {"target": target}, "rows": {"selection_id": kit.rows.selection_id}}})
    try:
        run = ml.launch(kit.env, kit.dataset, ml.prepare(kit.env, kit.dataset, req), "chat")
    except ApiError as exc:
        raise CantAnswer(exc.message) from None
    deadline = time.monotonic() + wait_s
    while run["status"] in ml.RUNNING and time.monotonic() < deadline:
        time.sleep(0.5)
        run = ml.get_run(kit.env.db, run["id"])
        progress = ml.to_run(kit.env.db, run)["progress"]
        status(f"What drives {target}: {progress['label']}…" if progress and progress.get("label") else f"What drives {target}…")
    if run["status"] in ml.RUNNING:
        return Reply(blocks=[text_block([text("I started the analysis of what drives "), label(target),
                                         text(". It's still running; ask again in a moment and the answer will be ready.")])],
                     focus={"run_id": run["id"]})
    if run["status"] != "done" and run["status"] != "outdated":
        raise CantAnswer(f"The analysis of what drives {target} failed: {run['error'] or 'no reason given'}.")
    mc = json.loads(run["model_card_json"])
    top = [i for i in mc["importance"] if i["value"] > 0][:10] or mc["importance"][:3]
    imp = memory_result(rid, f"permutation importance of run {run['id']}", [("feature", "VARCHAR"), ("importance", "DOUBLE")],
                        [[i["column"], i["value"]] for i in top])
    best = max(mc["baselines"], key=lambda b: b["value"])
    m = mc["model"]
    metric = {"accuracy": "accuracy", "macro_f1": "macro F1", "r2": "R²"}[m["metric"]]
    shown = (lambda v: f"{v * 100:.1f}%") if m["metric"] != "r2" else (lambda v: f"{v:.2f}")
    scores = memory_result(f"{rid}m", f"model card of run {run['id']}", [("measure", "VARCHAR"), ("value", "DOUBLE")],
                           [[f"model {metric}", m["value"]], [best["name"], best["value"]]])
    runs = _verdict_runs(mc, target, metric, shown, scores)
    named_top = top[:3]
    runs.append(text("The strongest factors are " if len(named_top) > 1 else "The strongest factor is "))
    for i, f in enumerate(named_top):
        if i:
            runs.append(text(" and " if i == len(named_top) - 1 else ", "))
        runs += [label(f["column"]), text(" ("), chip(imp, i, 1, f"{f['value']:.2f}"), text(")")]
    runs.append(text(". These are associations, not causes."))
    return Reply(blocks=[text_block(runs), table_block(imp)],
                 sources=[{"kind": "run", "run_id": run["id"],
                           "label": f"What drives {target}: {mc['chosen_model'].replace('_', ' ')} by "
                                    f"{mc['split']['folds']}-fold cross-validation on version {mc['version']}"}],
                 actions=[{"kind": "open_model_card", "run_id": run["id"]}],
                 focus={"run_id": run["id"], "target": target})


def _verdict_runs(mc: dict, target: str, metric: str, shown, scores: Result) -> list:
    """The verdict sentence of `ask_why`: row 0 of `scores` is the model's metric, row 1 the best simple
    rule's. When one column's rule does about as well as the model, it names that column: the signal is
    real and one column carries it, so the drivers aren't weak."""
    from sherlock.ml.analysis import LIFT

    runs = []
    m, best = mc["model"], max(mc["baselines"], key=lambda b: b["value"])
    floor = min(b["value"] for b in mc["baselines"])
    carried = best.get("column") and not best.get("target_encoded") and best["value"] - floor >= LIFT[m["metric"]]
    if mc["verdict"] != "beats_baseline" and carried:  # one strong column, not weak drivers
        runs += [label(best["column"]), text(f" alone predicts {target} about as well as the model: {metric} "),
                 chip(scores, 1, 1, shown(best["value"])), text(" against "), chip(scores, 0, 1, shown(m["value"])),
                 text(" for the model on rows it never saw. That column carries the signal; the others add little. ")]
    elif mc["verdict"] == "beats_baseline":
        runs += [text(f"A model can predict {target} better than simple rules: its {metric} on rows it never saw is "),
                 chip(scores, 0, 1, shown(m["value"])), text(" against "), chip(scores, 1, 1, shown(best["value"])),
                 text(" for the best simple rule. ")]
    elif mc["verdict"] == "weak":
        runs += [text(f"The signal is weak: the model's {metric} is "), chip(scores, 0, 1, shown(m["value"])),
                 text(" against "), chip(scores, 1, 1, shown(best["value"])), text(" for the best simple rule. ")]
    else:
        runs += [text(f"The model does no better than the best simple rule ({metric} "), chip(scores, 0, 1, shown(m["value"])),
                 text(" against "), chip(scores, 1, 1, shown(best["value"])), text("), so read these factors as weak. ")]
    return runs


# --- ask_model ------------------------------------------------------------------------------------

def pick_run(db, dataset, context: dict, resolved: dict, focus: dict | None):
    """The run a question is about: the focused widget's, the previous answer's, one on a column the
    message names, else the newest finished one."""
    ids = []
    wid = context.get("focused_widget_id")
    if wid:
        w = db.execute("SELECT run_id FROM widgets WHERE id = ? AND dataset_id = ?", (wid, dataset["id"])).fetchone()
        ids.append(w["run_id"] if w else None)
    ids.append((focus or {}).get("run_id"))
    for rid in [i for i in ids if i]:
        row = db.execute("SELECT * FROM runs WHERE id = ? AND status IN ('done', 'outdated')", (rid,)).fetchone()
        if row:
            return row
    runs = db.execute("SELECT * FROM runs WHERE dataset_id = ? AND status IN ('done', 'outdated') ORDER BY finished_at DESC",
                      (dataset["id"],)).fetchall()
    named = set(resolved["columns"].values())
    return next((r for r in runs if r["target"] in named), runs[0] if runs else None)


def ask_model(kit: Toolkit, question: str, resolved: dict, context: dict, focus: dict | None, rid: str) -> Reply:
    """Questions about a run: its model card as results for the composer; "who did it get wrong?"
    answered in code with the misclassified rows (out of fold) and a link to them in the CSV tab."""
    from sherlock.ml import runner as ml

    run = pick_run(kit.env.db, kit.dataset, context, resolved, focus)
    if run is None:
        raise CantAnswer("There's no analysis yet. Ask “what drives <a column>?”, or use a widget's analysis menu.")
    mc = json.loads(run["model_card_json"])
    source = {"kind": "run", "run_id": run["id"], "label": f"The model card of “what drives {mc['target']}” (version {mc['version']})"}
    if ONE_ROW.search(question):
        raise CantAnswer("Explaining one row's prediction needs per-row predictions, which aren't in this release.")
    if WRONG.search(question) and "misclassified" in mc:
        sel = ml.wrong_rows(kit.env.db, kit.env.settings, kit.dataset, run)
        res = _wrong_table(kit, sel, rid)
        counts = memory_result(f"{rid}n", f"out-of-fold predictions of run {run['id']}", [("measure", "VARCHAR"), ("value", "BIGINT")],
                               [["predicted wrong", mc["misclassified"]], ["rows", mc["rows"]["train"]]])
        runs = [text("The model got "), chip(counts, 0, 1), text(" of "), chip(counts, 1, 1),
                text(" rows wrong when each was predicted by a model that never saw it. Open them in the CSV tab to look for a pattern.")]
        return Reply(blocks=[text_block(runs), table_block(res)], sources=[source],
                     actions=[{"kind": "open_rows", "selection_id": sel["selection_id"]},
                              {"kind": "open_model_card", "run_id": run["id"]}],
                     focus={"run_id": run["id"], "selection_id": sel["selection_id"]})
    m = mc["model"]
    best = max(mc["baselines"], key=lambda b: b["value"])
    measures = [[f"model {m['metric']}", m["value"]], ["interval low", m["ci"][0]], ["interval high", m["ci"][1]]]
    measures += [[b["name"], b["value"]] for b in mc["baselines"]]
    measures.append(["lift over the best simple rule", m["lift_over_best_baseline"]])
    for k in ("auc", "mae"):
        if k in m:
            measures.append([k, m[k]])
    rate_rows = len(measures) if m["metric"] != "r2" else 0  # accuracy, F1, intervals, baselines, lift read as %
    measures.append(["rows used", mc["rows"]["train"]])
    if "misclassified" in mc:
        measures.append(["rows predicted wrong", mc["misclassified"]])
    card_res = memory_result(rid, f"model card of run {run['id']}: chosen model {mc['chosen_model']}, verdict {mc['verdict']} "
                                  f"({mc['verdict_text']}); best simple rule {best['name']}",
                             [("measure", "VARCHAR"), ("value", "DOUBLE")], measures)
    card_res.extra["formats"] = {f"{i}:1": ("pct" if i < rate_rows and measures[i][0] not in ("auc", "mae") else
                                            "int" if isinstance(measures[i][1], int) else "num") for i in range(len(measures))}
    results = [
        card_res,
        memory_result(f"{rid}i", f"permutation importance of run {run['id']}", [("feature", "VARCHAR"), ("importance", "DOUBLE")],
                      [[i["column"], i["value"]] for i in mc["importance"]]),
        memory_result(f"{rid}x", f"columns left out of run {run['id']}", [("column", "VARCHAR"), ("reason", "VARCHAR")],
                      [[e["column"], e["reason"]] for e in mc["excluded"]] or [["(none)", "every column was used"]]),
    ]
    if mc["warnings"]:
        results.append(memory_result(f"{rid}w", f"warnings of run {run['id']}", [("warning", "VARCHAR"), ("suggestion", "VARCHAR")],
                                     [[w["text"], w["suggestion"]] for w in mc["warnings"]]))
    if mc.get("alternatives"):
        results.append(memory_result(f"{rid}a", f"other models Auto tried in run {run['id']}", [("model", "VARCHAR"), ("score", "DOUBLE")],
                                     [[a["label"], a["value"]] for a in mc["alternatives"]]))
    return Reply(results=results, sources=[source], actions=[{"kind": "open_model_card", "run_id": run["id"]}],
                 focus={"run_id": run["id"]})


def _wrong_table(kit: Toolkit, sel: dict, rid: str) -> Result:
    """The first rows of the selection, with the selection attached for "Open these rows in CSV"."""
    sql = ws.selection_sql(kit.env.db, kit.dataset["id"], sel["selection_id"])
    template = f"SELECT * EXCLUDE (_quarantine_reason) FROM t WHERE {{{{rows}}}} AND {sql} ORDER BY _row_id LIMIT 20"
    res = kit._run(template, rid)
    res.total, res.selection_id = sel["row_count"], sel["selection_id"]
    return res


# --- ask_meaning ----------------------------------------------------------------------------------

def ask_meaning(kit: Toolkit, question: str, resolved: dict, card: dict, rid: str) -> Reply:
    """What a column means: what the data says (counts, common values, from queries) and, labelled
    apart, what such a column usually records (general knowledge, no digits)."""
    cols = {c["name"]: c for c in card["columns"]}
    names = mentioned(resolved, list(cols))
    if not names:  # a bare name in the question ("what is sibsp?")
        words = re.findall(r"[\w.]+", question.lower())
        names = [c for c in cols if c.lower() in words]
    if not names:
        raise CantAnswer("Which column? Name it, for example “what does pclass mean?”.")
    col = cols[names[0]]
    q = ident(col["name"])
    numeric = col["type"] in ("int", "float", "date", "datetime")
    facts = kit._run(f"SELECT count(*) AS rows, count({q}) AS filled, count(DISTINCT {q}) AS distinct_values"
                     + (f", min({q}) AS lowest, max({q}) AS highest" if numeric else "") + " FROM t WHERE {{rows}}", rid)
    common = kit._run(f"SELECT {q} AS value, count(*) AS n FROM t WHERE {{{{rows}}}} AND {q} IS NOT NULL "
                      f"GROUP BY 1 ORDER BY n DESC, 1 LIMIT 8", f"{rid}v")
    runs = [label(col["name"]), text(f" is a {TYPE_WORDS.get(col['type'], col['type'])} column ({ROLE_WORDS.get(col['role'], col['role'])}). "),
            chip(facts, 0, 1), text(" of "), chip(facts, 0, 0), text(" rows have a value, with "), chip(facts, 0, 2),
            text(" different values")]
    if numeric and facts.rows[0][3] is not None:
        runs += [text(" from "), chip(facts, 0, 3), text(" to "), chip(facts, 0, 4)]
    runs.append(text("."))
    blocks = [text_block(runs), table_block(common)]
    sources = [{"kind": "sql", "sql": facts.sql, "label": f"What the data says about {col['name']}"},
               {"kind": "sql", "sql": common.sql, "label": "Its most common values"}]
    about = f"name: {col['name']}\ntype: {col['type']}\nexamples: " + ", ".join(str(r[0])[:40] for r in common.rows)
    try:
        general = kit.llm.structured("medium", kit._messages(prompts.MEANING.format(
            column=col["name"], file=kit.dataset["name"], about=data_block(about))), Meaning, purpose="meaning",
            scope=kit.scope).value.general.strip()
    except (StructuredOutputError, LLMUnavailable, BudgetExceeded):
        general = None
    if general:
        block = text_block([text("In general (not from your data): "), text(general)])
        block["labeled"] = "general"
        blocks.append(block)
        sources.append({"kind": "general", "label": "General knowledge from the model, not computed from your data"})
    return Reply(blocks=blocks, sources=sources, focus={"columns": [col["name"]]})


# --- app_help -------------------------------------------------------------------------------------

STOP = set("a an the and or of to in on for with is are be it this that how do does i my me can what where when "
           "which why you your from as at by if into not".split())


def help_sections(folder: Path = HELP_DIR) -> list[dict]:
    out = []
    for f in sorted(folder.glob("*.md")):
        page, heading, lines = f.stem, None, []
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                page = line[2:].strip()
            elif line.startswith("## "):
                if heading:
                    out.append({"file": f.name, "page": page, "heading": heading, "text": " ".join(lines).strip()})
                heading, lines = line[3:].strip(), []
            elif line.strip():
                lines.append(line.strip())
        if heading:
            out.append({"file": f.name, "page": page, "heading": heading, "text": " ".join(lines).strip()})
    return out


def _tokens(s: str) -> set[str]:
    return {w.rstrip("s") for w in re.findall(r"[a-z]+", s.lower()) if w not in STOP and len(w) > 1}


def app_help(question: str, folder: Path = HELP_DIR) -> Reply:
    """Retrieval over `docs/help/*.md` (TRD §8.2): the best-matching section by shared words (headings
    count three times) and fuzzy heading similarity."""
    words = _tokens(question)
    scored = []
    for s in help_sections(folder):
        score = 3 * len(words & _tokens(s["heading"])) + len(words & _tokens(s["text"])) + len(words & _tokens(s["page"]))
        score += fuzz.partial_ratio(question.lower(), s["heading"].lower()) / 100
        scored.append((score, s))
    scored.sort(key=lambda x: -x[0])
    if not scored or scored[0][0] < 1.5:
        raise CantAnswer("I couldn't find that in the help. Ask about loading a file, cleaning, the dashboard, "
                         "analysis, the CSV tab, chat or exporting a notebook.")
    best = scored[0][1]
    runs = [{"type": "label", "ref": f"help:{best['file']}", "text": best["heading"]}, text(": " + best["text"])]
    also = [s for score, s in scored[1:3] if score >= max(1.5, scored[0][0] / 2)]
    if also:
        runs.append(text(" See also: " + "; ".join(s["heading"] for s in also) + "."))
    return Reply(blocks=[text_block(runs)],
                 sources=[{"kind": "help", "label": f"Help: {best['page']} › {best['heading']} (docs/help/{best['file']})"}])
