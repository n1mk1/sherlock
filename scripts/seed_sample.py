"""Make the cached sample (Implementation Plan D9.1): run the whole pipeline on Titanic once with the real
model, then save it as the seed that "Try with sample" clones (`api/samples/seed/titanic3/`).

    uv run --project api python scripts/seed_sample.py [--out DIR] [--keep-data]

The run happens in a throwaway data folder: import, clean it with the Cleaner, then ask what drives
survival so the sample has an analysis. The seed is the dataset's rows and files
(`sherlock/sample_seed.py`); paths in it are relative, so it works on any machine.

With `--keep-data` it starts from the current seed instead: the same cleaned data and steps (the
Cleaner's choices vary from run to run, and the docs cite this sample's), with its analyses run
again. That is what a fix to the ML code changes.
"""

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "/api/v1"


def wait(fn, what: str, timeout_s: float = 1800):
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        value = fn()
        if value:
            return value
        time.sleep(2)
    raise SystemExit(f"timed out waiting for {what}")


def all_done(client, ds: str) -> bool:
    return all(j["status"] in ("done", "failed", "cancelled") for j in client.get(f"{API}/jobs?dataset_id={ds}").json())


def rerun(client, ds: str) -> None:
    """`--keep-data`: the cloned seed's analyses run again. A done run is the cache's answer to the same
    request, so it's marked outdated first and the same request queues it again under its ID."""
    from sherlock.config import get_settings
    from sherlock.db.connection import connect

    db = connect(get_settings())
    try:
        runs = db.execute("SELECT recipe, method, scope_json, params_json FROM runs WHERE dataset_id = ?", (ds,)).fetchall()
        db.execute("UPDATE runs SET status = 'outdated' WHERE dataset_id = ?", (ds,))
        db.commit()
    finally:
        db.close()
    for r in runs:
        body = {"recipe": r["recipe"], "method": r["method"], "scope": json.loads(r["scope_json"]),
                "params": json.loads(r["params_json"])}
        res = client.post(f"{API}/datasets/{ds}/runs", json=body)
        assert res.status_code == 200, res.text
    print("running the analyses again…", flush=True)
    wait(lambda: all_done(client, ds), "the runs")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(ROOT / "api" / "samples" / "seed" / "titanic3"))
    parser.add_argument("--keep-data", action="store_true",
                        help="start from the seed in --out: keep its data and run its analyses again")
    args = parser.parse_args()
    out = Path(args.out)
    sys.path.insert(0, str(ROOT / "api"))

    with tempfile.TemporaryDirectory(prefix="sherlock-seed-") as tmp:
        os.environ.update(DATA_DIR=tmp, DATABASE_URL=f"sqlite:///{Path(tmp, 'sherlock.db').as_posix()}",
                          SAMPLE_SEED_DIR=str(out) if args.keep_data else "off", JOB_WORKERS="2", PURGE_INTERVAL_S="0")
        from fastapi.testclient import TestClient

        from sherlock.config import get_settings
        from sherlock.db.connection import connect
        from sherlock.llm.calls import by_role
        from sherlock.main import create_app
        from sherlock.sample_seed import snapshot

        get_settings.cache_clear()
        with TestClient(create_app()) as client:
            t0 = time.monotonic()
            ds = client.post(f"{API}/datasets/sample").json()["id"]
            if args.keep_data:
                assert client.get(f"{API}/datasets/{ds}").json()["status"] == "ready", "no seed to keep in --out"
                rerun(client, ds)
            else:
                wait(lambda: client.get(f"{API}/datasets/{ds}").json()["status"] == "offer", "the profile")
                r = client.post(f"{API}/datasets/{ds}/clean", json={})
                assert r.status_code == 201, r.text
                print("cleaning with the real model…", flush=True)
                wait(lambda: client.get(f"{API}/datasets/{ds}").json()["status"] in ("ready", "failed"), "the clean")
                with client.stream("POST", f"{API}/datasets/{ds}/chat",
                                   json={"text": "What drives survived?", "context": {"tab": "csv"}}) as s:
                    for _ in s.iter_lines():
                        pass
                wait(lambda: all_done(client, ds), "the last jobs")

            settings = get_settings()
            db = connect(settings)
            try:
                meta = snapshot(settings, db, ds, out)
                calls = by_role(db)
            finally:
                db.close()
            dataset = client.get(f"{API}/datasets/{ds}").json()
        get_settings.cache_clear()
    print(f"seed written to {out} in {time.monotonic() - t0:.0f} s: version {dataset['current_version']}, "
          f"{dataset['step_count']} steps, " + ", ".join(f"{n} {t}" for t, n in meta["counts"].items() if n))
    for c in calls:
        print(f"  model {c['role']}: {c['n']} calls, {c['p'] or 0} prompt and {c['c'] or 0} completion tokens")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
