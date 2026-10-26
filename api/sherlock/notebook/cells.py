"""Cell renderers for the exported notebook (TRD §7.7, App Flow §17.4): one function per cell kind.

Each returns nbformat cells. Code cells hold only code Sherlock already ran (a step's stored
`notebook_code`, a widget's compiled SQL) or plain glue; text is written by code, never a model.
"""

import json
import re

from nbformat.v4 import new_code_cell, new_markdown_cell

from sherlock.steps.replay import TYPING_SQL

PLOT_HELPERS = '''# Charts: one function draws every widget the way the dashboard does (greys, the point in the accent).
import matplotlib.pyplot as plt
from IPython.display import display

GREY, LIGHT, ACCENT = "#55575c", "#a9a69f", "#2f6b62"


def kpi_text(v, format=None):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—" if v is None else str(v)
    if f != f:
        return "—"
    if format == "pct":
        return f"{f:.1%}"
    return f"{f:,.0f}" if f.is_integer() else f"{f:,.2f}"


def plot(result, view, x=None, y=None, series=None, title=None, point=None, value=None, format=None):
    cols = list(result.columns)
    if view in ("kpi", "gauge"):  # as the app's KPI tile: the `value` column, else the first (not the count `n`)
        value = value if value in cols else cols[0]
        print(f"{title or value}: {kpi_text(result[value].iloc[0] if len(result) else None, format)}")
        return
    x = x if x in cols else cols[0]
    y = y if y in cols else (cols[1] if len(cols) > 1 else cols[0])
    if view == "table" or result.empty:
        display(result.head(50))
        return
    fig, ax = plt.subplots(figsize=(7, 3.4))
    if view in ("line", "area"):
        ax.plot(result[x], result[y], color=GREY)
        if view == "area":
            ax.fill_between(result[x], result[y], color=LIGHT, alpha=0.4)
    elif view == "scatter":
        ax.scatter(result[x], result[y], s=8, color=GREY, alpha=0.6)
    elif view == "heatmap" and series in cols:
        grid = result.pivot_table(index=series, columns=x, values=y, aggfunc="first")
        ax.imshow(grid.values, cmap="Greys", aspect="auto")
        ax.set_xticks(range(len(grid.columns)), [str(c) for c in grid.columns])
        ax.set_yticks(range(len(grid.index)), [str(i) for i in grid.index])
    elif view == "box" and {"q1", "median", "q3"} <= set(cols):
        stats = [{"label": str(r[x]), "whislo": r.get("lo", r.get("min")), "q1": r["q1"], "med": r["median"],
                  "q3": r["q3"], "whishi": r.get("hi", r.get("max")), "fliers": []} for _, r in result.iterrows()]
        ax.bxp(stats, showfliers=False)
    elif view in ("importance", "coefficients"):
        ax.barh(result[x].astype(str)[::-1], result[y][::-1], color=GREY)
    else:  # bar, histogram, and pie, ring and gauge drawn as bars
        colors = [ACCENT if point is not None and str(v) == str(point) else GREY for v in result[x]]
        ax.bar(result[x].astype(str), result[y], color=colors)
    ax.set_title(title or "", loc="left", fontsize=11)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    plt.tight_layout()
    plt.show()
'''


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def title(dataset_name: str, version: int, exported_at: str, app_version: str, steps: int, widgets: int,
          notes: list[str]) -> list:
    lines = [
        f"# {dataset_name} · version {version}",
        "",
        f"Exported from Sherlock {app_version} on {exported_at}. This notebook rebuilds version {version} "
        f"from the raw file ({steps} step{'s' if steps != 1 else ''}), then reruns the dashboard's "
        f"{widgets} widget{'s' if widgets != 1 else ''}.",
        "",
        "Every number below was computed by code. The cleaning steps were written by NVIDIA Nemotron models "
        "on Nebius Token Factory ([models](https://build.nvidia.com/nvidia)) and checked by code before Sherlock "
        "kept them; nothing here calls a model.",
    ]
    for note in notes:
        lines += ["", f"> {note}"]
    return [new_markdown_cell("\n".join(lines))]


def parameters(data_file: str, include_data: bool) -> list:
    where = ("" if include_data else
             "# Download the raw file from Sherlock (Export notebook → Include data) and put it next to this notebook.\n")
    return [new_code_cell(f'{where}DATA_PATH = "{data_file}"\nRANDOM_SEED = 42\n')]


def requirements(pins: str) -> list:
    packages = " ".join(p.strip() for p in pins.split(",") if p.strip())
    return [new_code_cell("# The library versions Sherlock used.\n"
                          "# %pip needs pip in this kernel's environment. In a uv venv, make it with `uv venv --seed`,\n"
                          "# or install these with `uv pip install` in a terminal and skip this cell.\n"
                          f"%pip install -q {packages}\n",
                          metadata={"tags": ["requirements"]})]


def helpers(source: str) -> list:
    return [new_code_cell(source)]


def load(options: dict, names: list[str], types: dict[str, str]) -> list:
    """Decode the raw file as the import did, read it all as text with DuckDB, add `_row_id` and
    `_quarantine_reason`, and give the columns the names the import gave them."""
    skip = options["skip_rows"] + max(options["header_row"] - 1, 0)
    header = "true" if options["header_row"] > 0 else "false"
    delim = options["delimiter"].replace("'", "''")
    if options.get("width"):  # a ragged file the import read with explicit text columns
        columns = "{{" + ", ".join(f"'c{i}': 'VARCHAR'" for i in range(1, options["width"] + 1)) + "}}"  # braces escaped: the cell is an f-string
        read = (f"read_csv('{{UTF8_PATH}}', delim='{delim}', quote='\\\"', escape='\\\"', header=false, "
                f"skip={skip + (1 if options['header_row'] > 0 else 0)}, auto_detect=false, columns={columns}, null_padding=true)")
    else:
        read = f"read_csv('{{UTF8_PATH}}', delim='{delim}', header={header}, skip={skip}, all_varchar=true, null_padding=true)"
    quarantine = ""
    if options.get("header_fields"):  # rows with more fields than the header were quarantined at import
        n = options["header_fields"]
        reason = f"extra fields: this row has more fields than the header's {n}"
        quarantine = (f"raw.loc[raw[{names[n:]!r}].notna().any(axis=1), \"_quarantine_reason\"] = {reason!r}\n")
    code = f'''# Load: decode the raw file ({options["encoding"]}) into a UTF-8 copy, then read it as Sherlock's import did.
from pathlib import Path

UTF8_PATH = Path(DATA_PATH).stem + ".utf8.csv"
Path(UTF8_PATH).write_text(Path(DATA_PATH).read_bytes().decode({options["encoding"]!r}), encoding="utf-8", newline="")
raw = duckdb.sql(f"SELECT * FROM {read}").df()
raw.columns = {names!r}
raw.insert(0, "_quarantine_reason", None)
raw.insert(0, "_row_id", range(1, len(raw) + 1))
{quarantine}types = {json.dumps(types)}
df = keep_types(raw, types)
print(f"Loaded {{len(df):,}} rows and {{len(df.columns) - 2}} columns.")
'''
    return [new_code_cell(code, metadata={"tags": ["load"]})]


def _impact_line(impact: dict) -> str:
    parts = [f"{impact.get('rows_in', 0):,} rows in, {impact.get('rows_out', 0):,} out",
             f"{impact.get('cells_changed', 0):,} cells changed"]
    if impact.get("quarantined"):
        parts.append(f"{impact['quarantined']:,} rows quarantined")
    if impact.get("rows_added"):
        parts.append(f"{impact['rows_added']:,} added")
    if impact.get("rows_deleted"):
        parts.append(f"{impact['rows_deleted']:,} deleted")
    return " · ".join(parts)


GATES = {"commit": "committed", "flag": "committed with a flag", "user": "made by hand"}


def step(s: dict) -> list:
    """A Markdown header and the step's code, then the store that the app makes after it."""
    who = {"system": "automatic", "cleaner": "the Cleaner", "user": "you", "chat": "chat"}.get(s["created_by"], s["created_by"])
    lines = [f"### Step {s['no']} · {s['summary']}", "",
             f"By {who}, {GATES.get(s['gate'] or '', s['gate'] or 'committed')}"
             + (f" (confidence {s['confidence']:.2f})" if s.get("confidence") is not None and s["created_by"] == "cleaner" else "")
             + ".  ", _impact_line(s["impact"]) + "."]
    if s.get("flag_reason"):
        lines += ["", f"Flag: {s['flag_reason']}"]
    for d in s.get("decisions") or []:
        if d.get("asked"):  # a step the user asked for in the cleaning plan, in their words
            lines += ["", f"You asked: {d['asked']}"]
        lines += ["", f"- **{d.get('question', '')}** {d.get('chosen', '')}" + (f". {d['reason']}" if d.get("reason") else "")]
    md = new_markdown_cell("\n".join(lines))
    typing = TYPING_SQL.match(s.get("code") or "") if s["kind"] == "clean" and s["created_by"] == "system" else None
    if typing:
        code = (f'rel = duckdb.sql("""\n{typing.group(1)}\n""")\n'
                "types = {c: str(t) for c, t in zip(rel.columns, rel.types)}\ndf = rel.df()\n")
    elif s["kind"] == "edit":
        code = s["notebook_code"].rstrip() + "\ndf = keep_types(df, types)\n"
    else:
        code = s["notebook_code"].rstrip() + "\ndf, types = store_step(df, types)\n"
    return [md, new_code_cell(code)]


def undo_note(s: dict, undone_no: int) -> list:
    return [new_markdown_cell(f"*Step {undone_no} was undone (step {s['no']}), so it isn't replayed here.*")]


def assertion(version: int, rows: int, types: dict[str, str]) -> list:
    users = len([c for c in types if c not in ("_row_id", "_quarantine_reason")])
    code = f'''# Check: the rebuilt DataFrame matches Sherlock's version {version}.
expected = {json.dumps(types)}
assert len(df) == {rows}, f"expected {rows:,} rows, got {{len(df):,}}"
assert list(df.columns) == list(expected), "the columns differ from the version"
assert types == expected, "a column's type differs from the version"
print("Rebuilt version {version}: {rows:,} rows × {users} columns, matching Sherlock.")
'''
    return [new_code_cell(code)]


def scope_text(spec: dict) -> str:
    rows = spec.get("scope", {}).get("rows", {})
    if rows.get("predicate"):
        return f"Rows: `{rows['predicate']}`"
    if rows.get("selection_id"):
        return "Rows: a saved selection"
    return "Rows: all rows"


def widget(w: dict, sql: str, output, point: str | None) -> list:
    """Markdown (title and scope), the SQL with its embedded table, and the chart."""
    spec = w["spec"]
    view = spec["view"]
    opts = view.get("options") or {}
    md = new_markdown_cell(f"## {w['title']}\n\n{scope_text(spec)} · view: {view['type']}")
    note = "# The dashboard's global filter isn't applied here; the widget's own rows are (in the WHERE clause).\n"
    data = new_code_cell(f'{note}t = df\nresult = duckdb.sql("""\n{sql}\n""").df()\nresult\n')
    data.outputs = [output]
    args = [f"{view['type']!r}"]
    for key in ("x", "y", "series") + (("value", "format") if view["type"] in ("kpi", "gauge") else ()):
        if opts.get(key):
            args.append(f"{key}={opts[key]!r}")
    args.append(f"title={w['title']!r}")
    if point is not None:
        args.append(f"point={point!r}")
    chart = new_code_cell(f"plot(result, {', '.join(args)})\n")
    return [md, data, chart]


def closing() -> list:
    return [new_markdown_cell(
        "## How to continue\n\n"
        "- `df` holds the cleaned data and `types` its column types; add cells below to keep exploring.\n"
        "- Query `df` with SQL as the widgets do: `t = df; duckdb.sql(\"SELECT … FROM t\").df()`.\n"
        "- The helpers cell near the top holds the cleaning functions the steps used, with docstrings.\n"
        "- Sherlock: https://sherlock-anw3.onrender.com"
    )]


def safe_name(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text)


def _runs_md(runs: list[dict], facts: dict, notes: list[str]) -> str:
    out = []
    for r in runs:
        if r.get("type") == "chip":
            if r.get("unverified"):
                notes.append(r.get("value", ""))
                out.append(f"{r.get('value', '')}*")
            else:
                f = facts.get(r.get("key") or "")
                out.append(f["formatted"] if f else r.get("value", ""))
        elif r.get("type") == "label":
            out.append(r.get("text") or r.get("ref", "").split(":")[-1])
        else:
            out.append(r.get("text", ""))
    return "".join(out).strip()


def _lines(runs: list[dict]) -> list[list[dict]]:
    out: list[list[dict]] = [[]]
    for r in runs:
        if r.get("type") == "text" and r.get("text") == "\n":
            out.append([])
        else:
            out[-1].append(r)
    return out


def card(c: dict, facts: dict, level: str = "###", stale: str | None = None) -> list:
    """A story card as Markdown (PRD NB-6): the headline as a heading, the body with every chip as
    its number from the fact sheet, related widgets, and the evidence queries in a closed details
    block. Numbers typed by hand get an asterisk and a footnote. `stale`: why the card isn't current
    (plan 1.3), said in italics under the heading, like an outdated run's note."""
    notes: list[str] = []
    lines = [f"{level} {_runs_md([r for b in c['headline']['blocks'] for r in b['runs']], facts, notes)}", ""]
    if stale:
        lines += [f"*{stale}*", ""]
    for b in c["body"]["blocks"]:
        if b.get("type") == "bullets":  # one item per line ("\n" runs split them, as the app shows them)
            lines += [f"- {_runs_md(item, facts, notes)}" for item in _lines(b["runs"]) if item]
            continue
        lines += [_runs_md(b["runs"], facts, notes), ""]
    web = any(r.get("type") == "label" and str(r.get("ref", "")).startswith("web:") for b in c["body"]["blocks"] for r in b["runs"])
    if web:  # a web answer (TRD §8.2 web_context): cited, with its sources above, never computed from the data
        lines += ["", "*From the web pages cited, retrieved on the dates shown; not computed from the data.*"]
    if c.get("related"):
        lines += ["", "Related: " + " · ".join(r["title"] for r in c["related"])]
    if notes:
        lines += ["", r"\* Typed by hand in Sherlock, not computed."]
    sqls = []
    for b in c["headline"]["blocks"] + c["body"]["blocks"]:
        for r in b["runs"]:
            f = facts.get(r.get("key") or "") if r.get("type") == "chip" else None
            if f and f.get("sql") and f["sql"] not in sqls:
                sqls.append(f["sql"])
    if sqls:
        lines += ["", "<details><summary>Evidence</summary>", ""]
        for s in sqls:
            lines += ["```sql", s, "```", ""]
        lines.append("</details>")
    return [new_markdown_cell("\n".join(lines).strip())]


def flow_intro(cards: int, notes: int) -> list:
    parts = ([f"{cards} {'card' if cards == 1 else 'cards'} written from other cards or from chat answers"] if cards else []) + \
            ([f"{notes} {'note' if notes == 1 else 'notes'}"] if notes else [])
    return [new_markdown_cell("## From the Flow canvas\n\n" + " and ".join(parts).capitalize() + ". "
                              "Each number in them is a fact computed above, with its query under Evidence.")]


def note(text: str) -> list:
    """A canvas note (PRD NB-6, Include canvas notes): the user's own words, quoted."""
    return [new_markdown_cell("> **Note**\n>\n" + "\n".join(f"> {line}" if line else ">" for line in text.strip().splitlines()))]


def run(title: str, card: dict, code: str, outdated: bool, metrics_output, baselines_output, importance_output) -> list:
    """An analysis (TRD §6.7, §7.7): a Markdown header with the excluded columns and their reasons,
    the run's `repro.py` inlined and called on the rebuilt `df` (its metrics and tables embedded from
    the run), and the importance chart."""
    from sherlock.ml.core import MODEL_LABELS

    lines = [f"## {title}", "",
             f"What drives **{card['target']}** · {scope_text({'scope': card.get('scope') or {}})} · "
             f"Auto picked {MODEL_LABELS.get(card['chosen_model'], card['chosen_model'])} by {card['split']['folds']}-fold "
             f"cross-validation (seed {card['split']['seed']})"
             + (f", keeping rows that share a `{card['split']['group']}` in one fold." if card["split"].get("group") else "."),
             "", f"**{card['verdict_text']}**", ""]
    if card["excluded"]:
        lines += ["Left out, with the reason:", ""] + [f"- `{e['column']}`: {e['reason']}" for e in card["excluded"]] + [""]
    if outdated:
        lines.append(f"*Outdated: the data changed after this ran on version {card['version']}. The numbers below are "
                     "from that run; running the cell on this data can give different ones.*")
    md = new_markdown_cell("\n".join(lines).strip())
    call = (f"{code.rstrip()}\n\n\n"
            "from IPython.display import display\n\n"
            "run_result = reproduce(df)\n"
            "m = run_result[\"metrics\"]\n"
            "print(f\"{m['metric']}: {m['value']:.3f} (95% interval {m['ci'][0]:.3f} to {m['ci'][1]:.3f}) "
            "on {run_result['rows']:,} rows\")\n"
            "display(pd.DataFrame(run_result[\"baselines\"]))\n"
            "run_result[\"importance\"]\n")
    cell = new_code_cell(call)
    cell.outputs = [metrics_output, baselines_output, importance_output]
    chart = new_code_cell(f"plot(run_result[\"importance\"].head(15), \"importance\", x=\"feature\", y=\"importance\", "
                          f"title={title!r})\n")
    return [md, cell, chart]


def metrics_text(card: dict) -> str:
    m = card["model"]
    return (f"{m['metric']}: {m['value']:.3f} (95% interval {m['ci'][0]:.3f} to {m['ci'][1]:.3f}) "
            f"on {card['rows']['train']:,} rows\n")
