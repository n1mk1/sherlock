"""Static checks before any execution (TRD §3.4), on the syntax tree rather than the text.

Rejected: imports outside the allowlist; calls to `__import__`, `eval`, `exec`, `open`,
`compile` and other escape hatches; any dunder attribute or name; any `read_*` / `to_*`
attribute except `to_datetime`, `to_numeric`, `to_timedelta`; attributes that reach the OS or
the file system through a library (`pd.io.common.os`, `np.load`, …). This is the first barrier,
not the only one: the worker restricts builtins and imports again, and on Linux runs as a user
that can't read `/data`.
"""

import ast
from dataclasses import dataclass

ALLOWED_MODULES = frozenset({"pandas", "numpy", "re", "math", "datetime", "rapidfuzz", "dateparser", "ftfy"})
# Read-only analysis for chat questions SQL can't express (`agent/analysis.py`) may also fit models and run tests.
ANALYSIS_MODULES = ALLOWED_MODULES | {"scipy", "sklearn"}
FORBIDDEN_NAMES = frozenset({
    "__import__", "eval", "exec", "open", "compile", "globals", "locals", "vars", "getattr", "setattr",
    "delattr", "breakpoint", "input", "exit", "quit", "memoryview",
    "os", "sys", "subprocess", "socket", "requests", "urllib", "importlib", "builtins", "shutil",
    "pathlib", "ctypes", "pickle", "marshal", "io",
})
FORBIDDEN_ATTRIBUTES = frozenset({
    "os", "sys", "subprocess", "socket", "builtins", "io", "shutil", "pathlib", "importlib", "ctypes",
    "pickle", "marshal", "system", "popen", "spawn", "fork", "eval", "exec", "compile",
    "load", "loads", "save", "savez", "savez_compressed", "savetxt", "loadtxt", "fromfile", "tofile",
    "memmap", "genfromtxt", "DataSource", "lib", "ctypeslib", "testing", "f2py", "distutils",
    "open", "get_handle", "urlopen", "pipe",
})
ALLOWED_TO = frozenset({"to_datetime", "to_numeric", "to_timedelta"})


@dataclass(frozen=True)
class Violation:
    line: int
    reason: str

    def __str__(self) -> str:
        return f"line {self.line}: {self.reason}"


def check(code: str, modules: frozenset[str] = ALLOWED_MODULES) -> list[Violation]:
    """All violations in `code` (empty list: allowed). A syntax error is a violation."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [Violation(exc.lineno or 0, f"syntax error: {exc.msg}")]
    found: list[Violation] = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in modules:
                    found.append(Violation(line, f"import of {alias.name!r} is not allowed"))
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            if node.level or module not in modules:
                found.append(Violation(line, f"import from {node.module!r} is not allowed"))
        elif isinstance(node, ast.Name):
            if node.id in FORBIDDEN_NAMES or node.id.startswith("__"):
                found.append(Violation(line, f"use of {node.id!r} is not allowed"))
        elif isinstance(node, ast.Attribute):
            attr = node.attr
            if attr.startswith("__"):
                found.append(Violation(line, f"dunder attribute {attr!r} is not allowed"))
            elif attr in FORBIDDEN_ATTRIBUTES:
                found.append(Violation(line, f"attribute {attr!r} is not allowed"))
            elif (attr.startswith("read_") or attr.startswith("to_")) and attr not in ALLOWED_TO:
                found.append(Violation(line, f"{attr!r} reads or writes outside the frame and is not allowed"))
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            found.append(Violation(line, "global and nonlocal are not allowed"))
    return found


MAX_LINES = 15
ROW_METHODS = {"iterrows", "itertuples"}


def style(code: str) -> list[str]:
    """Messages for code that is safe but not plain: a row loop, `iterrows`, `itertuples`, `apply(axis=1)`, or more
    than 15 non-empty lines. Only for chat commands, which the user reads before OK; the sandbox doesn't use it. Each
    message says the fix, so it can go straight back to the model. Code that doesn't parse is `check`'s job."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.While)):
            found.append(f"line {node.lineno}: a {'for' if isinstance(node, ast.For) else 'while'} loop. Use whole-column "
                         "pandas, no row loops: a string method on the column, or result.loc[mask, column] = value")
        elif isinstance(node, ast.Attribute) and node.attr in ROW_METHODS:
            found.append(f"line {node.lineno}: .{node.attr}() walks the rows. Use whole-column pandas, no row loops: "
                         "operate on the column, or result.loc[mask, column] = value")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "apply":
            axis = next((k.value for k in node.keywords if k.arg == "axis"), None)
            if isinstance(axis, ast.Constant) and axis.value in (1, "columns"):
                found.append(f"line {node.lineno}: .apply(..., axis=1) runs a function on every row. Use whole-column "
                             "pandas, no row loops: combine the columns directly, or np.where / result.loc[mask, column] = value")
    lines = sum(1 for ln in code.splitlines() if ln.strip())
    if lines > MAX_LINES:
        found.append(f"Make it shorter: {lines} lines, at most {MAX_LINES}. Drop what the request doesn't need "
                     "and use whole-column operations")
    return found
