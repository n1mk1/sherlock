"""Make the cached sample (Implementation Plan D9.1): run the whole pipeline on Titanic once with the real
model, then save it as the seed that "Try with sample" clones (`api/samples/seed/titanic3/`).

    uv run --project api python scripts/seed_sample.py [--out DIR]

The run happens in a throwaway data folder: import, clean it with the Cleaner, the dashboard, its
stories and analysis, then three cards on the canvas made sense of. The seed is the dataset's rows and
files (`sherlock/sample_seed.py`); paths in it are relative, so it works on any machine.
"""

import argparse
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(ROOT / "api" / "samples" / "seed" / "titanic3"))
    out = Path(parser.parse_args().out)
    sys.path.insert(0, str(ROOT / "api"))

    with tempfile.TemporaryDirectory(prefix="sherlock-seed-") as tmp:
        os.environ.update(DATA_DIR=tmp, DATABASE_URL=f"sqlite:///{Path(tmp, 'sherlock.db').as_posix()}",
                          SAMPLE_SEED_DIR="off", JOB_WORKERS="2", PURGE_INTERVAL_S="0")
        from fastapi.testclient import TestClient

        from sherlock.config import get_settings
        from sherlock.db.connection import connect
        from sherlock.main import create_app
        from sherlock.sample_seed import snapshot

        get_settings.cache_clear()
        with TestClient(create_app()) as client:
            t0 = time.monotonic()
            ds = client.post(f"{API}/datasets/sample").json()["id"]
            wait(lambda: client.get(f"{API}/datasets/{ds}").json()["status"] == "offer", "the profile")
            r = client.post(f"{API}/datasets/{ds}/clean", json={})
            assert r.status_code == 201, r.text
            print("cleaning with the real model…", flush=True)
            wait(lambda: client.get(f"{API}/datasets/{ds}").json()["status"] in ("ready", "failed"), "the clean and build")
            done = ("done", "failed", "cancelled")
            wait(lambda: all(j["status"] in done for j in client.get(f"{API}/jobs?dataset_id={ds}").json()), "stories and runs")

            # The canvas: the first three widget cards in a column, made sense of.
            cards = [c for c in client.get(f"{API}/datasets/{ds}/cards").json() if c["kind"] == "widget"][:3]
            canvas = client.get(f"{API}/datasets/{ds}/canvas").json()
            nodes = [{"id": f"seed{i}", "type": "text", "x": 0, "y": i * 280, "width": 240, "height": 250, "text": "",
                      "sherlock": {"card_id": c["id"]}} for i, c in enumerate(cards)]
            client.put(f"{API}/datasets/{ds}/canvas", json={"canvas": {"nodes": nodes, "edges": []}, "etag": canvas["etag"]})
            with client.stream("POST", f"{API}/datasets/{ds}/chat", json={
                    "text": "Make sense of this", "context": {"tab": "flow", "selected_card_ids": [c["id"] for c in cards]}}) as s:
                for _ in s.iter_lines():
                    pass
            wait(lambda: all(j["status"] in done for j in client.get(f"{API}/jobs?dataset_id={ds}").json()), "the last jobs")

            settings = get_settings()
            db = connect(settings)
            try:
                meta = snapshot(settings, db, ds, out)
                calls = db.execute("SELECT role, count(*) AS n, sum(prompt_tokens) AS p, sum(completion_tokens) AS c "
                                   "FROM llm_calls GROUP BY role").fetchall()
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
