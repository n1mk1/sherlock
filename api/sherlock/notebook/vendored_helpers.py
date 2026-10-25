"""The helpers cell (TRD §7.7, PRD NB-3): the cleaning helpers the notebook's steps use, copied
from `sherlock.cleaning.helpers`, plus the two functions that store a step the way the app does.

The app keeps each version as Parquet, and every step reads the previous version back into pandas
through DuckDB. The notebook repeats that round trip so its DataFrame matches the app's exactly:
- `keep_types(df, types)` casts every column to the version's DuckDB type (the load and edit
  batches, which the app applies with DuckDB and which never change a column's type);
- `store_step(result, types)` stores a cleaning step's result as the sandbox does
  (`sherlock.sandbox.worker.output_select`: a column keeps its type where pandas only changed it in
  transit) and returns the new types.
"""

import ast
import inspect
import textwrap

from sherlock.cleaning import helpers
from sherlock.sandbox import worker

KEEP_TYPES = '''
def keep_types(df, types):
    """`df` with each column cast to its DuckDB type in Sherlock's version (`types`: name → type),
    read back through DuckDB as the app reads every version."""
    cols = ", ".join(f"CAST({_q(c)} AS {t}) AS {_q(c)}" for c, t in types.items())
    return duckdb.sql(f"SELECT {cols} FROM df ORDER BY _row_id").df()


def store_step(result, types):
    """Store a cleaning step's `result` as Sherlock does and read it back: returns (df, types)."""
    rel = duckdb.sql(output_select(result, types).replace("FROM result_frame", "FROM result") + " ORDER BY _row_id")
    return rel.df(), {c: str(t) for c, t in zip(rel.columns, rel.types)}
'''


def _module_parts(module) -> tuple[list[str], dict[str, str], list[str]]:
    """(import lines, public function name → source, private definitions and constants in order)."""
    source = inspect.getsource(module)
    tree = ast.parse(source)
    imports, public, private = [], {}, []
    for node in tree.body:
        text = ast.get_source_segment(source, node)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append(text)
        elif isinstance(node, ast.FunctionDef):
            (private.append(text) if node.name.startswith("_") else public.__setitem__(node.name, text))
        elif isinstance(node, ast.Assign) and not any(getattr(t, "id", "") == "__all__" for t in node.targets):
            private.append(text)
    return imports, public, private


def helpers_cell(used: list[str]) -> str:
    """Source for the helpers cell: imports, the used helpers with what they need, and the two
    storage functions."""
    imports, public, private = _module_parts(helpers)
    lines = ["# Helpers copied from Sherlock: the cleaning helpers the steps below use, and how a step is stored.",
             "import duckdb"]
    lines += [i for i in imports if i != "import duckdb"]
    chosen = [name for name in helpers.__all__ if name in used]
    body = list(private) + [public[n] for n in chosen]
    worker_src = inspect.getsource(worker)
    tree = ast.parse(worker_src)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "INT_TYPES" for t in node.targets):
            body.append(ast.get_source_segment(worker_src, node))
        if isinstance(node, ast.FunctionDef) and node.name in ("_q", "output_select"):
            body.append(ast.get_source_segment(worker_src, node))
    body.append(textwrap.dedent(KEEP_TYPES).strip())
    return "\n".join(lines) + "\n\n\n" + "\n\n\n".join(body) + "\n"
