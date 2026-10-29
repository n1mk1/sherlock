"""Check a deployed Sherlock from the outside. Each `httpx` client is a
fresh browser: its own cookie, so its own anonymous user.

    uv run --project api python scripts/live_check.py [--url https://sherlock-anw3.onrender.com] [--files all|none]

It checks: /healthz; "Try with sample" is ready at once, already cleaned; a second user can't see the
first's data; the per-user rate limits answer 429; a chat answer is sourced; a cell edit saves as a new
version. With `--files all` it also uploads the five-file end-to-end set,
cleans or takes each as it is, exports each notebook and runs it here top to
bottom (the `%pip` cell skipped: this venv has the pins), checking it rebuilds the version.
"""

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

import httpx2 as httpx  # the API's HTTP client (an httpx fork with the same interface)

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "api" / "samples"
FILES = {"titanic3.csv": {}, "sales_dated.csv": {}, "wide_messy.csv": {"clean": True}, "reviews_text.csv": {},
         "broken_latin1.txt": {"options": {"header_row": 3}, "clean": True}}
API = "/api/v1"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print(f"{'ok  ' if ok else 'FAIL'} {name}{' · ' + detail if detail else ''}", flush=True)
    return ok


def client(url: str) -> httpx.Client:
    c = httpx.Client(base_url=url, timeout=120, follow_redirects=True)
    c.get(f"{API}/me").raise_for_status()  # the cookie first, as the app does
    return c


def wait(fn, timeout: float, every: float = 2):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(every)
    return None


def chat(c: httpx.Client, ds: str, text: str, **context) -> dict:
    with c.stream("POST", f"{API}/datasets/{ds}/chat", json={"text": text, "context": {"tab": "csv", **context}}) as r:
        event = None
        for line in r.iter_lines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: ") and event == "message":
                return json.loads(line[6:])
    return {}


def sample_checks(url: str) -> None:
    h = httpx.get(f"{url}/healthz", timeout=60).json()
    check("healthz", h.get("ok") is True and h["llm"]["reachable"], f"version {h.get('version')}, models {h.get('models')}")
    a, b = client(url), client(url)
    t0 = time.monotonic()
    r = a.post(f"{API}/datasets/sample")
    ds = r.json()
    check("Try with sample is ready at once", r.status_code == 201 and ds["status"] == "ready",
          f"{time.monotonic() - t0:.1f} s, v{ds.get('current_version')}")
    check("the sample arrives cleaned", ds.get("step_count", 0) >= 2, f"{ds.get('step_count')} steps")
    check("a second browser can't see the first's dataset", b.get(f"{API}/datasets/{ds['id']}").status_code == 404
          and b.get(f"{API}/datasets").json() == [])
    check("nor its rows or report", all(b.get(p).status_code == 404 for p in (
        f"{API}/datasets/{ds['id']}/rows", f"{API}/datasets/{ds['id']}/report")))
    b2 = b.post(f"{API}/datasets/sample").json()
    check("the second browser gets its own copy", b2["id"] != ds["id"])

    # Rate limits: 10 model-bearing requests a minute. Aimed at a dataset that doesn't exist,
    # so no model is called: the limit is checked before the route looks the dataset up.
    codes = [b.post(f"{API}/datasets/ds_nope/chat", json={"text": "hi"}).status_code for _ in range(11)]
    check("the per-user model rate limit answers 429", codes[:10] == [404] * 10 and codes[10] == 429, str(codes))
    other = a.get(f"{API}/datasets").status_code
    check("another user isn't limited by it", other == 200)

    t0 = time.monotonic()
    msg = chat(a, ds["id"], "average fare by class")
    sql = [s for s in msg.get("sources", []) if s.get("sql")]
    check("a chat answer is sourced", bool(msg.get("blocks")) and bool(sql), f"{time.monotonic() - t0:.1f} s: {msg.get('text', '')[:80]}")

    rows = a.get(f"{API}/datasets/{ds['id']}/rows?limit=1").json()
    saved = a.post(f"{API}/datasets/{ds['id']}/edits", json={"base_version": rows["version"], "edits": [
        {"row_id": rows["rows"][0]["_row_id"], "column": "fare", "value": "500"}]})
    check("a cell edit saves as a new version", saved.status_code == 201
          and a.get(f"{API}/datasets/{ds['id']}").json()["current_version"] == rows["version"] + 1)


def file_checks(url: str) -> None:
    import nbclient
    import nbformat

    c = client(url)
    for name, how in FILES.items():
        t0 = time.monotonic()
        data = {"options": json.dumps(how["options"])} if how.get("options") else {}
        r = c.post(f"{API}/datasets", files={"file": (name, (SAMPLES / name).read_bytes(), "text/csv")}, data=data)
        if not check(f"{name}: uploads", r.status_code == 201, r.text[:120] if r.status_code != 201 else ""):
            continue
        ds = r.json()["id"]
        st = wait(lambda: (s := c.get(f"{API}/datasets/{ds}").json()["status"]) in ("offer", "failed") and s, 300)
        if st != "offer":
            check(f"{name}: profiles", False, str(st))
            continue
        c.post(f"{API}/datasets/{ds}/clean", json={}) if how.get("clean") else c.post(f"{API}/datasets/{ds}/use-as-is")
        st = wait(lambda: (s := c.get(f"{API}/datasets/{ds}").json()["status"]) in ("ready", "failed") and s, 1200)
        wait(lambda: all(j["status"] in ("done", "failed", "cancelled") for j in c.get(f"{API}/jobs?dataset_id={ds}").json()), 900)
        d = c.get(f"{API}/datasets/{ds}").json()
        check(f"{name}: {'cleaned and ' if how.get('clean') else ''}ready", st == "ready",
              f"{time.monotonic() - t0:.0f} s, v{d['current_version']}, {d['step_count']} steps")
        out = c.post(f"{API}/datasets/{ds}/exports/notebook", json={"include_data": False}).json()
        out = wait(lambda: (e := c.get(f"{API}/exports/{out['export_id']}").json())["status"] in ("done", "failed") and e, 300, 1)
        if not check(f"{name}: notebook exports", bool(out) and out["status"] == "done", str(out and out.get("error"))):
            continue
        with tempfile.TemporaryDirectory() as tmp:
            nb = nbformat.reads(c.get(out["download_url"]).text, as_version=4)
            (Path(tmp) / f"{Path(name).stem}-raw.csv").write_bytes(c.get(f"{API}/datasets/{ds}/raw.csv").content)
            for cell in nb.cells:
                if cell.cell_type == "code" and cell.source.lstrip().startswith("%pip"):
                    cell.source = "pass  # the pins are installed here"
            try:
                nbclient.NotebookClient(nb, timeout=600, kernel_name="python3", resources={"metadata": {"path": tmp}}).execute()
                ok, why = True, f"{sum(x.cell_type == 'code' for x in nb.cells)} code cells"
            except Exception as exc:  # noqa: BLE001 - report it, keep checking the other files
                ok, why = False, str(exc).splitlines()[-1][:160]
            check(f"{name}: the notebook runs top to bottom and rebuilds v{out['version']}", ok, why)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="https://sherlock-anw3.onrender.com")
    p.add_argument("--files", default="none", choices=["all", "none"])
    args = p.parse_args()
    sample_checks(args.url)
    if args.files == "all":
        file_checks(args.url)
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)} of {len(results)} checks passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
