"""Reproduction code for a run (TRD §6.7, PRD NB-5): a self-contained `reproduce(df, seed=42)` that
selects the run's rows with DuckDB, lists the features and the exclusions with their reasons, and
trains, scores and explains the winning model with the code of `sherlock/ml/core.py`, copied in.

The runner gets the model card's metrics by executing this same text, so the notebook, which runs
it on the rebuilt DataFrame, reports the same numbers.
"""

import ast
import inspect

from sherlock.ml import core
from sherlock.ml.plan import Plan

CORE_FUNCTIONS = ("prepare", "preprocessor", "make_model", "folds", "metric_name", "score", "pipeline", "evaluate",
                  "baselines", "importance", "run")


def core_source() -> str:
    """The imports, constants and functions of `core` that a run needs, as one block."""
    source = inspect.getsource(core)
    tree = ast.parse(source)
    parts = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            parts.append(ast.get_source_segment(source, node))
        elif isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "FOLDS" for t in node.targets):
            parts.append(ast.get_source_segment(source, node))
        elif isinstance(node, ast.FunctionDef) and node.name in CORE_FUNCTIONS:
            parts.append(ast.get_source_segment(source, node))
    return "\n\n\n".join(parts)


def render(plan: Plan, model: str, alternatives: list[dict], run_id: str, version: int, n_folds: int = core.FOLDS) -> str:
    """The run's `repro.py`."""
    excluded = "\n".join(f"#   {e['column']}: {e['reason']}" for e in plan.excluded) or "#   none"
    others = ", ".join(f"{core.MODEL_LABELS.get(a['model'], a['model'])} ({a['metric']} {a['mean']:.3f})" for a in alternatives) \
        or "none"
    sample = ""
    if plan.sample:
        sample = (f"    # The scope had more than {plan.sample['n']:,} rows, so the run used a random sample of them (seed {plan.sample['seed']}).\n"
                  f"    data = data.sample(n={plan.sample['n']}, random_state=seed).sort_values(\"_row_id\")\n")
    sql = f"SELECT * FROM t WHERE {plan.rows_sql} ORDER BY _row_id"
    return f'''# Reproduces Sherlock run {run_id} (driver analysis on version {version}).
# Auto tried: {others}. The winner, {core.MODEL_LABELS.get(model, model)}, is reproduced here.
import duckdb

{core_source()}


def reproduce(df, seed=42):
    """What drives {plan.target}: the same rows, features, folds and model as the app."""
    t = df
    data = duckdb.sql({sql!r}).df()  # the run's rows (quarantined rows excluded)
    data = data[data[{plan.target!r}].notna()]
{sample}    # Features used: {", ".join(plan.features)}
    # Left out, with the reason:
{excluded}
    return run(data, {plan.target!r}, {plan.numeric!r}, {plan.categorical!r}, {plan.high_card!r}, {plan.task!r}, {model!r}, seed, n_folds={n_folds})
'''


def execute(code: str, df):
    """Run a run's reproduction code on `df` (the version's data) and return its result."""
    scope: dict = {}
    exec(compile(code, "<repro>", "exec"), scope)  # noqa: S102 - code rendered by Sherlock, never by a model
    return scope["reproduce"](df)
