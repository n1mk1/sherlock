"""The `sherlock` command (Implementation Plan §4, D3.5).

    uv run sherlock clean <file.csv | sample>    import a CSV and run the Cleaner headless
    uv run sherlock eval corruption [--sets a,b] the cleaning benchmark (markdown table)
    uv run sherlock eval ask|ml|grounding|notebook
    uv run sherlock export notebook <dataset_id> --out out.ipynb

Commands run the app in-process against the configured `DATA_DIR` and `DATABASE_URL` (the `.env`),
with the real model unless `LLM_MOCK` is set. A CLI run is its own anonymous user.
"""

import argparse
import sys
import time
from pathlib import Path

NOT_BUILT = {
    "ask": "D4.3 (the chat agent)",
    "ml": "D7 (the ML runner)",
    "grounding": "D6 (story cards)",
    "notebook": "D5.6 (the notebook exporter)",
}


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
    p_eval.add_argument("which", choices=["corruption", *NOT_BUILT])
    p_eval.add_argument("--sets", default="", help="comma-separated benchmark sets (corruption)")
    p_export = sub.add_parser("export", help="export a dataset")
    p_export.add_argument("what", choices=["notebook"])
    p_export.add_argument("dataset_id")
    p_export.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    if args.command == "clean":
        return clean(args.source, args.timeout)
    if args.command == "eval":
        if args.which != "corruption":
            _print(f"`sherlock eval {args.which}` isn't built yet: it comes with Implementation Plan {NOT_BUILT[args.which]}.")
            return 2
        from sherlock.eval.corruption import run

        _print(run([s for s in args.sets.split(",") if s] or None))
        return 0
    if args.command == "export":
        _print("`sherlock export notebook` isn't built yet: it comes with Implementation Plan D5.6.")
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
