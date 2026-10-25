"""The typing step (TRD §7.1 step 3b, PRD PROF-1): code, not LLM, committed as step 1 on every path.

A column is cast only if its inferred type is int, float, bool, date or datetime and at least 99% of
its values (sentinels aside) cast losslessly: formatting the cast value back reproduces the source,
so codes with leading zeros stay text. In those columns only, sentinels (`N/A`, `null`, `?`, `-`,
blank, …) become NULL first, then the column is cast. A value that doesn't cast losslessly becomes
NULL and its row is quarantined (`type: <column>`); lineage keeps the original text. A float with
more than 15 significant digits, a timestamp with a non-UTC offset and one with sub-microsecond
fractions don't cast losslessly (DOUBLE and TIMESTAMP can't hold them). `verify` checks the statement
before it commits, and its results are the step's verifiers.

The step's `code` is one DuckDB statement over the frame `df` (`result = duckdb.sql(...).df()`),
so the app (over the version's Parquet, exposed as `df`) and the exported notebook (over the
DataFrame `df`) cast identically.
"""

import duckdb

from sherlock.profile.datacard import build_frame, load_frame
from sherlock.profile.infer import SENTINEL_STRINGS, THRESHOLD
from sherlock.storage import sql_path

CAST_TYPES = ("int", "float", "bool", "date", "datetime")
TRUE_WORDS = ("true", "t", "yes", "y")
FALSE_WORDS = ("false", "f", "no", "n")
FLOAT_DIGITS = 15
OFFSET = r"[0-9]:[0-9]{2}(:[0-9]{2})?([.,][0-9]+)?\s*([+-][0-9]{2}(:?[0-9]{2})?|Z)$"  # a time with a UTC offset
UTC = r"(Z|[+-]00(:?00)?)$"
SUB_MICRO = r"[0-9]:[0-9]{2}:[0-9]{2}[.,][0-9]{7,}"


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _lit(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _words(words) -> str:
    return ", ".join(_lit(w) for w in sorted(words))


def _value(col: str) -> str:
    """The cell as trimmed text, with sentinels as NULL."""
    c = _q(col)
    return f"CASE WHEN lower(trim({c})) IN ({_words(SENTINEL_STRINGS)}) THEN NULL ELSE trim({c}) END"


def _cast(col: str, kind: str, fmt: str | None) -> str:
    """The lossless cast of the cleaned value: NULL when the value doesn't cast without loss."""
    v = _value(col)
    if kind == "int":
        return (f"CASE WHEN CAST(TRY_CAST({v} AS BIGINT) AS VARCHAR) = regexp_replace({v}, '^[+]', '') "
                f"THEN TRY_CAST({v} AS BIGINT) END")
    if kind == "float":
        # A DOUBLE holds 15 significant digits exactly; a value with more would be rounded.
        digits = f"length(trim(regexp_replace(regexp_replace({v}, '[eE].*$', ''), '[^0-9]', '', 'g'), '0'))"
        return (f"CASE WHEN NOT regexp_matches({v}, '^[+-]?0[0-9]') AND {digits} <= {FLOAT_DIGITS} "
                f"THEN TRY_CAST({v} AS DOUBLE) END")
    if kind == "bool":
        return (f"CASE WHEN lower({v}) IN ({_words(TRUE_WORDS)}) THEN TRUE "
                f"WHEN lower({v}) IN ({_words(FALSE_WORDS)}) THEN FALSE END")
    target = "DATE" if kind == "date" else "TIMESTAMP"
    cast = (f"TRY_CAST({v} AS {target})" if not fmt or fmt == "ISO8601"
            else f"CAST(TRY_STRPTIME({v}, {_lit(fmt)}) AS {target})")
    # TIMESTAMP keeps no offset and only microseconds: a non-UTC offset or finer fractions would be lost.
    return (f"CASE WHEN regexp_matches({v}, {_lit(OFFSET)}) AND NOT regexp_matches({v}, {_lit(UTC)}) THEN NULL "
            f"WHEN regexp_matches({v}, {_lit(SUB_MICRO)}) THEN NULL ELSE {cast} END")


def plan(conn: duckdb.DuckDBPyConnection) -> dict[str, str]:
    """column → cast expression, for the columns that should be typed (conn holds the version as `t`;
    the expressions only name columns, so they run the same over `df`)."""
    df, types, _ = load_frame(conn)
    frame = build_frame(df, types)
    chosen: dict[str, str] = {}
    for name, col in frame.columns.items():
        if col.type not in CAST_TYPES or types.get(name, "VARCHAR") != "VARCHAR":
            continue
        expr = _cast(name, col.type, col.date_format)
        present, ok = conn.execute(
            f"SELECT count({_value(name)}), count({expr}) FROM t WHERE _quarantine_reason IS NULL"
        ).fetchone()
        if present and ok / present >= THRESHOLD:
            chosen[name] = expr
    return chosen


def statement(columns: list[str], casts: dict[str, str]) -> str:
    """The SELECT over `df` that types the chosen columns and quarantines rows that didn't cast."""
    fails = " ".join(
        f"WHEN {_value(c)} IS NOT NULL AND {casts[c]} IS NULL THEN {_lit('type: ' + c)}" for c in casts
    )
    select = ["_row_id", f"coalesce(_quarantine_reason, CASE {fails} END) AS _quarantine_reason"]
    for c in columns:
        select.append(f"{casts[c]} AS {_q(c)}" if c in casts else _q(c))
    return "SELECT\n  " + ",\n  ".join(select) + "\nFROM df\nORDER BY _row_id"


def verify(conn: duckdb.DuckDBPyConnection, typed: str, casts: dict[str, str]) -> dict[str, str]:
    """Check the typed output (`typed`, a table expression) against its source (the view `df`): it keeps
    every row (`row_ledger`), and no value of a usable row turned NULL unless its row is quarantined
    (`lossless`). It reads the output the commit already wrote, so the statement doesn't run twice."""
    rows_in = conn.execute("SELECT count(*) FROM df").fetchone()[0]
    rows_out = conn.execute(f"SELECT count(*) FROM {typed}").fetchone()[0]
    sources = ", ".join(f"{_value(c)} AS _src{i}" for i, c in enumerate(casts))
    lost_any = " OR ".join(f"(a._src{i} IS NOT NULL AND s.{_q(c)} IS NULL)" for i, c in enumerate(casts))
    lost = conn.execute(
        f"SELECT count(*) FROM (SELECT _row_id, {sources} FROM df WHERE _quarantine_reason IS NULL) a "
        f"JOIN {typed} s USING (_row_id) WHERE s._quarantine_reason IS NULL AND ({lost_any})").fetchone()[0]
    return {"row_ledger": "pass" if rows_in == rows_out else "fail", "lossless": "pass" if lost == 0 else "fail"}


def code_for(sql: str) -> str:
    return f'result = duckdb.sql("""\n{sql}\n""").df()\n'


def produce(sql: str, settings, casts: dict[str, str] | None = None, checks: dict | None = None):
    """Write the typed version. With `casts` and `checks`, also verify it into `checks`; a failed check
    raises, so the commit stops and nothing is written."""
    from sherlock.storage import new_duckdb

    def run(old, out) -> None:
        conn = new_duckdb(settings)
        try:
            conn.execute(f"CREATE VIEW df AS SELECT * FROM read_parquet({sql_path(old)})")
            conn.execute(f"COPY ({sql}) TO {sql_path(out)} (FORMAT PARQUET, COMPRESSION ZSTD)")
            if casts and checks is not None:
                checks.update(verify(conn, f"read_parquet({sql_path(out)})", casts))
                if "fail" in checks.values():
                    raise RuntimeError(f"the typing step failed its own checks: {checks}")
        finally:
            conn.close()
    return run


def summary(casts: dict[str, str]) -> str:
    names = list(casts)
    shown = ", ".join(names[:6]) + (f" and {len(names) - 6} more" if len(names) > 6 else "")
    return f"Typed {len(names)} column{'s' if len(names) != 1 else ''} from text: {shown}"


def apply(ctx, dataset, job_id: str | None = None) -> dict | None:
    """Commit the typing step on version 1 if the dataset has no steps yet. Returns the step, or None
    when there is nothing to type (or the dataset already has steps, e.g. a retried profile job)."""
    from sherlock.steps.commit import StepSpec, commit_step
    from sherlock.storage import dataset_dir

    if dataset["current_version"] != 1 or ctx.db.execute(
        "SELECT 1 FROM steps WHERE dataset_id = ? LIMIT 1", (dataset["id"],)
    ).fetchone():
        return None
    folder = dataset_dir(ctx.settings, dataset["user_id"], dataset["id"])
    v1 = ctx.db.execute("SELECT * FROM versions WHERE dataset_id = ? AND version = 1", (dataset["id"],)).fetchone()
    with ctx.cache.connection(dataset["id"], 1, folder / v1["parquet_path"]) as conn:
        casts = plan(conn)
        columns = [r[0] for r in conn.execute("DESCRIBE t").fetchall() if r[0] not in ("_row_id", "_quarantine_reason")]
    if not casts:
        return None
    sql = statement(columns, casts)
    checks: dict[str, str] = {}  # filled by produce before the step is stored
    code = code_for(sql)
    spec = StepSpec(
        kind="clean", summary=summary(casts), created_by="system", code=code, notebook_code=code + "df = result\n",
        column_targets=list(casts), confidence=1.0, gate="commit", job_id=job_id,
        decisions=[{"question": "Which columns hold numbers, true/false values or dates?",
                    "chosen": ", ".join(casts), "alternatives": ["keep every column as text"],
                    "reason": "at least 99% of each column's values convert without loss"}],
        verifiers=checks,
    )
    step, _ = commit_step(ctx, dataset["id"], 1, spec, produce(sql, ctx.settings, casts, checks))
    return step
