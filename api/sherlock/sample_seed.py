"""The cached sample (Implementation Plan D9.1, PRD P0-11): "Try with sample" in seconds.

`scripts/seed_sample.py` runs the whole pipeline on Titanic once with the real model (import, the
Cleaner, the dashboard, stories, the analysis, a canvas with a synthesis) and `snapshot` saves the
result as a seed: every row of the dataset's tables in `rows.json` and its folder's files. The seed
ships in the image (`api/samples/seed/titanic3/`). `POST /datasets/sample` then `clone`s it for the
user: every ID gets a fresh one (and every reference to it, in any column or JSON, and in the folder's
paths and text files), the rows are inserted under the user, and the files copied. Paths in the
database are relative to the dataset folder, so a seed made on one machine works on another.
"""

import json
import re
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sherlock.config import REPO_ROOT, Settings
from sherlock.db.util import new_id, now_iso
from sherlock.storage import dataset_dir, folder_bytes

DEFAULT_SEED = REPO_ROOT / "api" / "samples" / "seed" / "titanic3"
ID = re.compile(r"\b([a-z]{2,4})_([0-9A-Z]{26})\b")
# Parents before children (foreign keys). `datasets` is the dataset's own row; the rest by dataset_id.
TABLES = ("datasets", "versions", "datacards", "steps", "lineage", "user_edited_cells", "issues", "selections", "runs",
          "widgets", "layouts", "fact_sheets", "relations", "cards", "canvases", "jobs", "job_events", "value_index")
SKIP_COLUMNS = {"job_events": ("id",)}  # autoincrement: the database gives the copy its own
SKIP_FILES = (".lock", "exports")
TEXT_FILES = (".json", ".py", ".txt", ".md")


def seed_dir(settings: Settings) -> Path | None:
    """The seed to clone, or None (then the sample is imported and built the slow way)."""
    if settings.sample_seed_dir == "off":
        return None
    path = Path(settings.sample_seed_dir) if settings.sample_seed_dir else DEFAULT_SEED
    return path if (path / "rows.json").is_file() else None


def snapshot(settings: Settings, db: sqlite3.Connection, dataset_id: str, out: Path) -> dict:
    """Write the dataset's rows and files as a seed in `out` (replacing what was there)."""
    ds = db.execute("SELECT * FROM datasets WHERE id = ?", (dataset_id,)).fetchone()
    rows: dict[str, list[dict]] = {}
    for table in TABLES:
        where = "id = ?" if table == "datasets" else "dataset_id = ?"
        order = "ORDER BY id" if table == "job_events" else ""
        rows[table] = [dict(r) for r in db.execute(f"SELECT * FROM {table} WHERE {where} {order}", (dataset_id,))]  # noqa: S608
    for job in rows["jobs"]:
        job["owner_pid"] = None  # "<hostname>:<pid>:…" of the machine that built the seed; the seed is public
    if out.exists():
        shutil.rmtree(out)
    files = out / "files"
    src = dataset_dir(settings, ds["user_id"], dataset_id)
    shutil.copytree(src, files, ignore=shutil.ignore_patterns(*SKIP_FILES))
    meta = {"user_id": ds["user_id"], "dataset_id": dataset_id, "made_at": now_iso(),
            "counts": {t: len(v) for t, v in rows.items()}}
    (out / "rows.json").write_text(json.dumps({"meta": meta, "rows": rows}, default=str), encoding="utf-8")
    return meta


def _remapper(seed: dict, user_id: str):
    """old ID → new ID for every ID in the seed's rows, in any column or JSON (canvas node and edge IDs
    live only in the canvas JSON); the seed's user becomes this user."""
    mapping = {seed["meta"]["user_id"]: user_id}
    for table, rows in seed["rows"].items():
        for r in rows:
            for v in r.values():
                if isinstance(v, str):
                    for m in ID.finditer(v):
                        if m.group(0) not in mapping:
                            mapping[m.group(0)] = new_id(m.group(1))

    def remap(value):
        return ID.sub(lambda m: mapping.get(m.group(0), m.group(0)), value) if isinstance(value, str) else value

    return mapping, remap


def clone(settings: Settings, db: sqlite3.Connection, user_id: str, seed_path: Path, name: str) -> sqlite3.Row:
    """The seed as a new dataset of `user_id`, with fresh IDs; returns its `datasets` row."""
    seed = json.loads((seed_path / "rows.json").read_text(encoding="utf-8"))
    mapping, remap = _remapper(seed, user_id)
    new_ds = mapping[seed["meta"]["dataset_id"]]
    now = now_iso()
    expires = (datetime.now(UTC) + timedelta(days=settings.dataset_ttl_days)).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    target = dataset_dir(settings, user_id, new_ds)
    target.parent.mkdir(parents=True, exist_ok=True)
    files = seed_path / "files"
    for f in sorted(files.rglob("*")):
        rel = remap(f.relative_to(files).as_posix())  # run folders carry their run's ID
        dest = target / rel
        if f.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        elif f.suffix in TEXT_FILES:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(remap(f.read_text(encoding="utf-8")), encoding="utf-8")
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, dest)
    size = folder_bytes(target)

    db.execute("BEGIN IMMEDIATE")
    try:
        for table in TABLES:
            skip = SKIP_COLUMNS.get(table, ())
            for r in seed["rows"].get(table, []):
                row = {k: remap(v) for k, v in r.items() if k not in skip}
                if table == "datasets":
                    row.update(name=name, created_at=now, last_opened_at=None, deleted_at=None, expires_at=expires,
                               folder_bytes=size, is_sample=1, last_tab=None)
                if table == "job_events":
                    row["created_at"] = now  # the cleaning log is replayed from these; they live 24 h like any
                cols = ", ".join(row)
                db.execute(f"INSERT INTO {table} ({cols}) VALUES ({', '.join('?' for _ in row)})",  # noqa: S608
                           tuple(json.dumps(v) if isinstance(v, (dict, list)) else v for v in row.values()))
        db.execute("UPDATE users SET storage_bytes = storage_bytes + ? WHERE id = ?", (size, user_id))
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        shutil.rmtree(target, ignore_errors=True)
        raise
    return db.execute("SELECT * FROM datasets WHERE id = ?", (new_ds,)).fetchone()
