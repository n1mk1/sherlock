"""The `sherlock` command (Implementation Plan §4, D3.5).

    uv run sherlock clean <file.csv | sample>    import a CSV and run the Cleaner headless
    uv run sherlock eval corruption [--sets a,b] the cleaning benchmark (markdown table)
    uv run sherlock eval ask [--sets titanic3.csv] [--file f.yaml]  the ask-anything eval (markdown table)
    uv run sherlock eval notebook [--sets a.csv,b.csv | all] export each file's notebook and run it in a fresh venv
    uv run sherlock eval ml                      the planted-truth ML cases (markdown table)
    uv run sherlock eval web [--sets a.csv] [--live | --record] web answers: on, failing and off (markdown table);
                                                 offline on recorded fixtures unless --live (needs TAVILY_API_KEY)
    uv run sherlock export notebook <dataset_id> --out out.ipynb
    uv run sherlock llm stats [--days N] [--json]    per purpose and role: p50/p95 latency, tokens, repair, fail and fallback rates
    uv run sherlock detectors check [--rows N]   every registered detector, packs included, against the contract

Commands run the app in-process against the configured `DATA_DIR` and `DATABASE_URL` (the `.env`),
with the real model unless `LLM_MOCK` is set. A CLI run is its own anonymous user. `llm stats` only
reads the database (opened read-only) and starts no app.
"""

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

NOT_BUILT: dict[str, str] = {}  # evals the plan names that aren't built yet, with the item they come with


def _print(text: str) -> None:
    sys.stdout.buffer.write((text + "\n").encode("utf-8", errors="replace"))
    sys.stdout.flush()


def clean(source: str, timeout_s: float) -> int:
    from fastapi.testclient import TestClient

    from sherlock.main import create_app

    api = "/api/v1"
    with TestClient(create_app()) as client:
        if source == "sample":
            ds = client.post(f"{api}/datasets/sample").json()
        else:
            path = Path(source)
            with path.open("rb") as fh:
                r = client.post(f"{api}/datasets", files={"file": (path.name, fh, "text/csv")})
            if r.status_code >= 400:
                _print(f"Import failed: {r.json()['error']['message']}")
                return 1
            ds = r.json()
        _print(f"Imported {ds['name']} as {ds['id']}")
        ds = _wait(lambda: (d := client.get(f"{api}/datasets/{ds['id']}").json())["status"] in ("offer", "failed") and d,
                   timeout_s)
        if ds["status"] == "failed":
            _print(f"Profiling failed: {ds['error']}")
            return 1
        job = client.post(f"{api}/datasets/{ds['id']}/clean", json={}).json()
        _print(f"Cleaning (job {job['id']})…")
        seen = 0
        while True:
            entries = client.get(f"{api}/jobs/{job['id']}/log").json()["entries"]
            for e in entries[seen:]:
                chips = " · ".join(f"[{c['label']}]" if c["chosen"] else c["label"] for c in e.get("candidates") or [])
                _print(f"  {e['icon']:7} {e.get('column') or '':14} {e['text']}" + (f"  ({e['detail']})" if e.get("detail") else "")
                       + (f"\n          {chips}" if chips else ""))
            seen = len(entries)
            state = client.get(f"{api}/jobs/{job['id']}").json()
            if state["status"] in ("done", "failed", "cancelled"):
                break
            time.sleep(1)
        report = client.get(f"{api}/datasets/{ds['id']}/report").json()
        c = report["counts"]
        _print(f"Ended by {report['ended_by']}: {c['found']} issues found, {c['fixed']} fixed, {c['flagged']} flagged, "
               f"{c['skipped']} skipped, {c['rows_deleted']} rows deleted; v{report['from_version']} → v{report['to_version']}")
        for s in report["steps"]:
            _print(f"  step {s['no']} [{s['gate']}] {s['summary']}")
        return 0 if state["status"] == "done" else 1


def export_notebook(dataset_id: str, out: Path) -> int:
    """Export a dataset's notebook from the configured database, as the app's exporter does."""
    import nbformat

    from sherlock.config import get_settings
    from sherlock.db.connection import connect
    from sherlock.notebook.exporter import NotebookOptions, build
    from sherlock.storage import VersionConnections

    settings = get_settings()
    db = connect(settings)
    cache = VersionConnections(settings)
    try:
        dataset = db.execute("SELECT * FROM datasets WHERE id = ? AND deleted_at IS NULL", (dataset_id,)).fetchone()
        if dataset is None:
            _print(f"No dataset {dataset_id}.")
            return 1
        built = build(settings, db, cache, dataset, NotebookOptions())
        nbformat.write(built.nb, str(out))
        _print(f"Wrote {out} (version {built.version}: {built.counts['steps']} steps, {built.counts['runs']} analyses).")
        return 0
    finally:
        cache.close()
        db.close()


def llm_stats(days: float | None, as_json: bool) -> int:
    """`sherlock llm stats`: the model-call log summed per purpose and per role (TRD §14). The database
    is opened read-only, so it can run against a live app's file."""
    from sherlock.config import get_settings
    from sherlock.db.connection import sqlite_path
    from sherlock.llm.calls import stats, stats_table

    path = sqlite_path(get_settings().database_url).resolve()
    if not path.exists():
        _print(f"No database at {path}.")
        return 1
    db = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        out = stats(db, days)
    finally:
        db.close()
    _print(json.dumps(out, indent=1) if as_json else stats_table(out))
    return 0


def _wait(fn, timeout_s: float):
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        value = fn()
        if value:
            return value
        time.sleep(1)
    raise SystemExit("timed out")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sherlock", description="Sherlock's command line.")
    sub = parser.add_subparsers(dest="command", required=True)
    p_clean = sub.add_parser("clean", help="import a CSV (or 'sample') and clean it headless")
    p_clean.add_argument("source")
    p_clean.add_argument("--timeout", type=float, default=900)
    p_eval = sub.add_parser("eval", help="run a benchmark")
    p_eval.add_argument("which", choices=["corruption", "ask", "notebook", "ml", "web", *NOT_BUILT])
    p_eval.add_argument("--sets", default="", help="comma-separated benchmark sets (corruption) or sample files (ask)")
    p_eval.add_argument("--file", default="", help="ask: a questions file (default samples/eval/ask_questions.yaml)")
    live = p_eval.add_mutually_exclusive_group()
    live.add_argument("--live", action="store_true", help="web: real Nemotron and real Tavily (needs TAVILY_API_KEY)")
    live.add_argument("--record", action="store_true", help="web: real Nemotron, recorded Tavily; rewrites the Nemotron fixtures")
    p_export = sub.add_parser("export", help="export a dataset")
    p_export.add_argument("what", choices=["notebook"])
    p_export.add_argument("dataset_id")
    p_export.add_argument("--out", required=True)
    p_llm = sub.add_parser("llm", help="the model-call log")
    p_llm.add_argument("what", choices=["stats"])
    p_llm.add_argument("--days", type=float, default=None, help="only the last N days (default: the whole log)")
    p_llm.add_argument("--json", action="store_true", help="print JSON instead of markdown tables")
    p_det = sub.add_parser("detectors", help="the detector registry")
    p_det.add_argument("what", choices=["check"])
    p_det.add_argument("--rows", type=int, default=200_000, help="rows of the frame the time budget runs on")
    args = parser.parse_args(argv)

    if args.command == "clean":
        return clean(args.source, args.timeout)
    if args.command == "eval":
        if args.which == "ask":
            from sherlock.eval.ask import run as run_ask

            _print(run_ask([s for s in args.sets.split(",") if s] or None, args.file or None))
            return 0
        if args.which == "notebook":
            from sherlock.eval.notebook import END_TO_END
            from sherlock.eval.notebook import run as run_notebook

            sets = [s for s in args.sets.split(",") if s]
            _print(run_notebook(END_TO_END if sets == ["all"] else sets or None))
            return 0
        if args.which == "web":
            from sherlock.eval.web import run as run_web

            text, ok = run_web([s for s in args.sets.split(",") if s] or None,
                               mode="live" if args.live else "record" if args.record else "offline")
            _print(text)
            return 0 if ok else 1
        if args.which == "ml":
            from sherlock.eval.planted import run as run_planted

            _print(run_planted())
            return 0
        if args.which != "corruption":
            _print(f"`sherlock eval {args.which}` isn't built yet: it comes with Implementation Plan {NOT_BUILT[args.which]}.")
            return 2
        from sherlock.eval.corruption import run

        _print(run([s for s in args.sets.split(",") if s] or None))
        return 0
    if args.command == "export":
        return export_notebook(args.dataset_id, Path(args.out))
    if args.command == "llm":
        return llm_stats(args.days, args.json)
    if args.command == "detectors":
        return detectors_check(args.rows)
    return 2


def detectors_check(rows: int) -> int:
    """Run the contract (TRD §14) on every registered detector, with the packs `DETECTOR_PLUGINS` allows,
    as a markdown table; exit 1 when any detector fails, so a pack can be checked when it's installed."""
    from sherlock.cleaning import contract, registry
    from sherlock.config import get_settings

    registry.configure(get_settings())
    big = contract.big_frame(rows)
    lines = ["| Detector | Source | Result |", "|---|---|---|"]
    failed = 0
    for spec in registry.all():
        problems = contract.check(spec, big)
        failed += bool(problems)
        result = "; ".join(f"{name}: {why}" for name, why in problems) or "passes"
        lines.append(f"| {spec.id} | {spec.source} | {result.replace('|', '/')} |")
    refused = registry.packs()["refused"]
    lines += [f"| {p['name']} (pack) | refused | {p['reason'].replace('|', '/')} |" for p in refused]
    total = contract.total_seconds(registry.enabled(), contract.big_frame(contract.TOTAL_ROWS))
    slow = total > contract.TOTAL_SECONDS
    lines += ["", f"Every enabled check on {contract.TOTAL_ROWS:,} rows: {total:.1f} s (budget {contract.TOTAL_SECONDS:g} s)"
                  + (": over budget" if slow else "")]
    pairs = contract.overlaps(registry.all())
    lines += ["", "| Damage of | Also flagged by | Column |", "|---|---|---|"] + [f"| {a} | {b} | {c} |" for a, b, c in pairs]
    _print("\n".join(lines))
    return 1 if failed or refused or slow else 0


if __name__ == "__main__":
    raise SystemExit(main())
