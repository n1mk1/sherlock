"""Write the sample's exported notebook to `docs/examples/` (Implementation Plan D9.2), so it can be read on
GitHub: "Try with sample" (the cached seed) in a throwaway data folder, then Export notebook with every
option on but the data, which sits next to it as `titanic3-raw.csv` in the same folder.

    uv run --project api python scripts/example_notebook.py
"""

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "/api/v1"


def main() -> int:
    out_dir = ROOT / "docs" / "examples"
    sys.path.insert(0, str(ROOT / "api"))
    with tempfile.TemporaryDirectory(prefix="sherlock-example-") as tmp:
        os.environ.update(DATA_DIR=tmp, DATABASE_URL=f"sqlite:///{Path(tmp, 'sherlock.db').as_posix()}",
                          SAMPLE_SEED_DIR="", JOB_WORKERS="2", PURGE_INTERVAL_S="0")
        from fastapi.testclient import TestClient

        from sherlock.config import get_settings
        from sherlock.main import create_app

        get_settings.cache_clear()
        with TestClient(create_app()) as client:
            ds = client.post(f"{API}/datasets/sample").json()
            out = client.post(f"{API}/datasets/{ds['id']}/exports/notebook",
                              json={"include_data": True, "include_cards": True, "include_notes": True, "include_runs": True}).json()
            end = time.monotonic() + 120
            while out["status"] not in ("done", "failed") and time.monotonic() < end:
                time.sleep(0.5)
                out = client.get(f"{API}/exports/{out['export_id']}").json()
            if out["status"] != "done":
                raise SystemExit(f"export failed: {out.get('error')}")
            nb = client.get(out["download_url"])
            name = nb.headers["content-disposition"].split("filename=")[-1].strip('"; ')
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / name).write_bytes(nb.content)
            shutil.copyfile(ROOT / "api" / "samples" / "titanic3.csv", out_dir / "titanic3-raw.csv")
            print(f"wrote docs/examples/{name} ({len(nb.content):,} bytes) and docs/examples/titanic3-raw.csv; counts {out['counts']}")
        get_settings.cache_clear()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
