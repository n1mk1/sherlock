"""The sandbox worker (TRD §3.4): `python -I -m sherlock.sandbox.worker`, one process per run.

Protocol: one JSON object on stdin `{input, output, code, cpu_s, mem_mb}`; the worker loads the
input Parquet as `df`, runs `code` with only `pd`, `np`, `df` and the cleaning helpers
(`sherlock.cleaning.helpers`) in scope, expects a DataFrame in `result`, writes it to `output`, and
prints one JSON line:
`{ok, rows_in, rows_out, columns_added, columns_removed, error, traceback_tail, stdout_tail, flags}`.

A column the code didn't mean to retype keeps its input type on the way out: pandas reads a
nullable integer column as float and a DATE as a timestamp, so such columns are cast back when
that loses nothing. `flags` is `result.attrs["sherlock_flags"]` from `flag_rows`.

Defences inside the process, on top of the static check: CPU and address-space limits (POSIX),
sockets disabled, proxies pointed nowhere, a builtins table without file, eval or import escape
hatches, and imports limited to the allowlist.
"""

import builtins
import contextlib
import io
import json
import os
import sys
import traceback

TRACEBACK_LINES = 8
STDOUT_CHARS = 2000
SAFE_BUILTINS = (
    "abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter", "float", "format", "frozenset",
    "hash", "int", "isinstance", "issubclass", "iter", "len", "list", "map", "max", "min", "next", "pow",
    "print", "range", "repr", "reversed", "round", "set", "slice", "sorted", "str", "sum", "tuple", "zip",
    "True", "False", "None", "Exception", "ValueError", "TypeError", "KeyError", "IndexError",
    "ZeroDivisionError", "ArithmeticError", "RuntimeError", "StopIteration", "AttributeError",
    "NotImplementedError", "callable", "chr", "ord", "hex", "bin", "oct",
)  # no type/object: `type(x).__subclasses__()` is a classic escape if the static check were bypassed


def apply_cpu_limit(cpu_s: int) -> None:
    try:
        import resource
    except ImportError:  # Windows dev machines: the parent's wall-clock timeout still applies
        return
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 1))


def _address_space_bytes() -> int:
    with open("/proc/self/status") as status:
        for line in status:
            if line.startswith("VmSize:"):
                return int(line.split()[1]) * 1024
    return 0


@contextlib.contextmanager
def memory_budget(mem_mb: int):
    """Cap the address space at (current size + `mem_mb`) while the generated code runs, then lift it.

    Applied around `exec` only: DuckDB, which the worker itself uses to read and write Parquet,
    reserves large virtual memory for its threads and can't run under an address-space limit.
    Only the soft limit is lowered, so it can be restored; the generated code can't reach
    `resource` (not on the allowlist) to lift it itself.
    """
    try:
        import resource
    except ImportError:
        yield
        return
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    current = _address_space_bytes()
    limit = current + mem_mb * 1024 * 1024 if current else soft
    if hard != resource.RLIM_INFINITY:
        limit = min(limit, hard)
    resource.setrlimit(resource.RLIMIT_AS, (limit, hard))
    try:
        yield
    finally:
        resource.setrlimit(resource.RLIMIT_AS, (soft, hard))


def block_network() -> None:
    import socket

    class NoNetwork(socket.socket):
        def __init__(self, *args, **kwargs):
            raise PermissionError("network access is disabled in the sandbox")

    socket.socket = NoNetwork
    socket.create_connection = lambda *a, **k: (_ for _ in ()).throw(PermissionError("network access is disabled"))
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY"):
        os.environ[var] = "http://127.0.0.1:9"


def restricted_globals(df):
    import numpy as np
    import pandas as pd

    from sherlock.sandbox.static_check import ALLOWED_MODULES

    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level or name.split(".")[0] not in ALLOWED_MODULES:
            raise ImportError(f"import of {name!r} is not allowed in the sandbox")
        return real_import(name, globals, locals, fromlist, level)

    from sherlock.cleaning import helpers

    safe = {name: getattr(builtins, name) for name in SAFE_BUILTINS if hasattr(builtins, name)}
    safe["__import__"] = guarded_import
    scope = {"__builtins__": safe, "pd": pd, "np": np, "df": df}
    scope.update({name: getattr(helpers, name) for name in helpers.__all__})
    return scope


INT_TYPES = ("BIGINT", "INTEGER", "SMALLINT", "TINYINT", "HUGEINT", "UBIGINT", "UINTEGER")


def _q(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def output_select(result, input_types: dict[str, str]) -> str:
    """The SELECT that writes `result`, casting columns back to their input type where pandas
    changed the type only in transit (nullable ints → float, DATE → timestamp, all-missing → object)."""
    import pandas as pd

    parts = []
    for column in result.columns:
        s = result[column]
        original = input_types.get(column)
        expr = _q(column)
        if column == "_row_id":
            expr = f"CAST({expr} AS BIGINT)"
        elif column == "_quarantine_reason":
            expr = f"CAST({expr} AS VARCHAR)"
        elif original is not None:
            present = s.dropna()
            if present.empty:
                expr = f"CAST({expr} AS {original})"
            elif original in INT_TYPES and s.dtype.kind == "f" and bool((present % 1 == 0).all()):
                expr = f"CAST({expr} AS {original})"
            elif original == "DATE" and s.dtype.kind == "M" and bool((present.dt.normalize() == present).all()):
                expr = f"CAST({expr} AS DATE)"
            elif original.startswith("TIMESTAMP") and s.dtype.kind == "M":
                expr = f"CAST({expr} AS {original})"
            elif original == "BOOLEAN" and s.dtype == object and present.map(lambda v: isinstance(v, bool)).all():
                expr = f"CAST({expr} AS BOOLEAN)"
            elif original == "VARCHAR" and s.dtype == object and pd.api.types.infer_dtype(present) == "string":
                expr = f"CAST({expr} AS VARCHAR)"
        parts.append(f"{expr} AS {_q(column)}")
    return "SELECT " + ", ".join(parts) + " FROM result_frame"



def run(request: dict) -> dict:
    apply_cpu_limit(int(request.get("cpu_s", 30)))
    import duckdb  # loaded before the network block; it only reads and writes the two files

    block_network()
    reader = duckdb.connect(":memory:")
    df = reader.execute("SELECT * FROM read_parquet(?)", [request["input"]]).df()
    input_types = {r[0]: str(r[1]) for r in reader.execute("DESCRIBE SELECT * FROM read_parquet(?)", [request["input"]]).fetchall()}
    reader.close()
    rows_in, columns_in = len(df), list(df.columns)
    scope = restricted_globals(df)
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out), memory_budget(int(request.get("mem_mb", 2048))):
            exec(compile(request["code"], "<step>", "exec"), scope)
    except MemoryError:
        return {"ok": False, "error": "MemoryError: the step used more memory than the sandbox allows",
                "rows_in": rows_in, "stdout_tail": out.getvalue()[-STDOUT_CHARS:]}
    except BaseException as exc:  # noqa: BLE001 - every failure is reported, never raised
        tail = traceback.format_exception(type(exc), exc, exc.__traceback__)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "rows_in": rows_in,
                "traceback_tail": "".join(tail[-TRACEBACK_LINES:]), "stdout_tail": out.getvalue()[-STDOUT_CHARS:]}
    import pandas as pd

    result = scope.get("result")
    if not isinstance(result, pd.DataFrame):
        return {"ok": False, "error": "the code must leave a DataFrame in `result`", "rows_in": rows_in,
                "stdout_tail": out.getvalue()[-STDOUT_CHARS:]}
    writer = duckdb.connect(":memory:")
    writer.register("result_frame", result)
    select = output_select(result, input_types)
    writer.execute(f"COPY ({select}) TO '{request['output'].replace(chr(39), chr(39) * 2)}' (FORMAT PARQUET)")
    writer.close()
    flags = result.attrs.get("sherlock_flags") or {}
    return {
        "ok": True,
        "rows_in": rows_in,
        "rows_out": len(result),
        "columns_added": [c for c in result.columns if c not in columns_in],
        "columns_removed": [c for c in columns_in if c not in result.columns],
        "error": None,
        "traceback_tail": None,
        "stdout_tail": out.getvalue()[-STDOUT_CHARS:],
        "flags": {str(k): [int(i) for i in v][:10000] for k, v in flags.items()},
    }


def main() -> int:
    request = json.loads(sys.stdin.read())
    try:
        response = run(request)
    except MemoryError:
        response = {"ok": False, "error": "MemoryError: the step used more memory than the sandbox allows"}
    except BaseException as exc:  # noqa: BLE001
        response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    sys.stdout.write(json.dumps(response, default=str) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
