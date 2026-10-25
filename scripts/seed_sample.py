"""Make the cached sample (Implementation Plan D9.1): run the whole pipeline on Titanic once with the real
model, then save it as the seed that "Try with sample" clones (`api/samples/seed/titanic3/`).

    uv run --project api python scripts/seed_sample.py [--out DIR] [--keep-data]

The run happens in a throwaway data folder: import, clean it with the Cleaner, the dashboard, its
stories and analysis, then three cards on the canvas made sense of. The seed is the dataset's rows and
files (`sherlock/sample_seed.py`); paths in it are relative, so it works on any machine.

With `--keep-data` it starts from the current seed instead: the same cleaned data, steps and widgets
(the Cleaner's choices vary from run to run, and the docs cite this sample's), with its analyses run
again and every card and the synthesis written again. That is what a fix to the ML, stories or
synthesis code changes.
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


def all_done(client, ds: str) -> bool:
    return all(j["status"] in ("done", "failed", "cancelled") for j in client.get(f"{API}/jobs?dataset_id={ds}").json())


def retell(client, ds: str) -> None:
    """`--keep-data`: the cloned seed's analyses run again (a done run is the cache's answer to the same
    request, so it's marked outdated first and Re-run queues it again under its ID), and every other
    widget card, the overview and then the synthesis are written again."""
    from sherlock.config import get_settings
    from sherlock.db.connection import connect
    from sherlock.jobs.stories import queue_stories

    widgets = client.get(f"{API}/datasets/{ds}/widgets").json()["widgets"]
    ml = [w["id"] for w in widgets if w["spec"]["op"]["type"] == "ml"]
    db = connect(get_settings())
    try:
        db.execute("UPDATE runs SET status = 'outdated' WHERE dataset_id = ?", (ds,))
        dataset = db.execute("SELECT * FROM datasets WHERE id = ?", (ds,)).fetchone()
        queue_stories(db, dataset, [w["id"] for w in widgets if w["id"] not in ml], "refresh")
        db.commit()
    finally:
        db.close()
    for wid in ml:  # each run tells its own widget's card when it finishes
        r = client.post(f"{API}/widgets/{wid}/rerun")
        assert r.status_code == 200, r.text
    print("running the analyses and telling the cards again…", flush=True)
    wait(lambda: all_done(client, ds), "the runs and stories")
    retell_syntheses(client, ds)


def retell_syntheses(client, ds: str, tries: int = 3) -> None:
    """Write each synthesis card again, up to `tries` times until the model writes it: the seed is what
    every visitor sees first, and the fallback only lists the cards' headlines."""
    for cid in [c["id"] for c in client.get(f"{API}/datasets/{ds}/cards").json() if c["kind"] == "synthesis"]:
        for _ in range(tries):
            r = client.post(f"{API}/cards/{cid}/refresh")
            assert r.status_code == 201, r.text
            wait(lambda: all_done(client, ds), "the synthesis")
            if client.get(f"{API}/cards/{cid}").json()["narrated_by"]:
                break
        client.post(f"{API}/cards/{cid}/dismiss-badge")  # Refresh marks a card "changed", which every clone would show


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(ROOT / "api" / "samples" / "seed" / "titanic3"))
    parser.add_argument("--keep-data", action="store_true",
                        help="start from the seed in --out: keep its data, run its analyses again and write its cards again")
    args = parser.parse_args()
    out = Path(args.out)
    sys.path.insert(0, str(ROOT / "api"))

    with tempfile.TemporaryDirectory(prefix="sherlock-seed-") as tmp:
        os.environ.update(DATA_DIR=tmp, DATABASE_URL=f"sqlite:///{Path(tmp, 'sherlock.db').as_posix()}",
                          SAMPLE_SEED_DIR=str(out) if args.keep_data else "off", JOB_WORKERS="2", PURGE_INTERVAL_S="0")
        from fastapi.testclient import TestClient

        from sherlock.config import get_settings
        from sherlock.db.connection import connect
        from sherlock.main import create_app
        from sherlock.sample_seed import snapshot

        get_settings.cache_clear()
        with TestClient(create_app()) as client:
            t0 = time.monotonic()
            ds = client.post(f"{API}/datasets/sample").json()["id"]
            if args.keep_data:
                assert client.get(f"{API}/datasets/{ds}").json()["status"] == "ready", "no seed to keep in --out"
                retell(client, ds)
            else:
                wait(lambda: client.get(f"{API}/datasets/{ds}").json()["status"] == "offer", "the profile")
                r = client.post(f"{API}/datasets/{ds}/clean", json={})
                assert r.status_code == 201, r.text
                print("cleaning with the real model…", flush=True)
                wait(lambda: client.get(f"{API}/datasets/{ds}").json()["status"] in ("ready", "failed"), "the clean and build")
                wait(lambda: all_done(client, ds), "stories and runs")

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
                wait(lambda: all_done(client, ds), "the last jobs")

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
