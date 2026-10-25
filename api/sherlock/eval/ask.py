"""The ask-anything eval (TRD §14, Implementation Plan D4.3): `samples/eval/ask_questions.yaml`.

Each file is imported in a throwaway data directory, built with "Use as is", and its questions are
asked in order through `POST /chat` in one thread. An answer passes when it shows the expected
value (within the tolerance), contains the expected rows, or reports the expected row count. The
eval also counts unsourced answers: a number, table or chart with no SQL behind it (PRD ASK-3: this
must be 0). It uses the real model unless `LLM_MOCK` is set.
"""

import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
QUESTIONS = SAMPLES / "eval" / "ask_questions.yaml"
DEFAULT_TOL = 0.005
API = "/api/v1"


@dataclass
class Outcome:
    dataset: str
    question: str
    ok: bool
    got: str
    expected: str
    seconds: float
    unsourced: bool


def load(path: Path = QUESTIONS) -> dict[str, list[dict]]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def close(got, want: float, tol: float) -> bool:
    if isinstance(got, bool) or not isinstance(got, (int, float)):
        try:
            got = float(str(got).replace(",", "").rstrip("%"))
        except ValueError:
            return False
    if want == 0:
        return abs(got) <= tol
    if abs(got - want) <= abs(want) * tol:
        return True
    return 0 < want <= 1 and abs(got / 100 - want) <= abs(want) * tol  # a percentage of a rate


def numbers(blocks: list[dict]) -> list:
    """Every value the answer shows: number blocks first, then single-cell tables, then every cell."""
    out = [b["value"] for b in blocks if b["type"] == "number"]
    tables = [b for b in blocks if b["type"] == "table"] + [b["data"] for b in blocks if b["type"] == "chart"]
    out += [t["rows"][0][-1] for t in tables if len(t["rows"]) == 1 and t["rows"][0]]
    out += [v for t in tables for row in t["rows"] for v in row]
    return out


def row_maps(blocks: list[dict]) -> list[dict[str, list]]:
    """Each table or chart as {first column as text: the row's other values}."""
    maps = []
    for b in blocks:
        t = b if b["type"] == "table" else b.get("data") if b["type"] == "chart" else None
        if t and t["rows"]:
            maps.append({_key(r[0]): r[1:] for r in t["rows"]})
    return maps


def _key(v) -> str:
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v)[:10] if isinstance(v, str) and len(v) >= 10 and v[4:5] == "-" else str(v)


def check(message: dict, expect: dict) -> tuple[bool, str]:
    blocks = message.get("blocks") or []
    tol = float(expect.get("tol", DEFAULT_TOL))
    if "value" in expect:
        vals = numbers(blocks)
        hit = next((v for v in vals if close(v, float(expect["value"]), tol)), None)
        return hit is not None, str(hit if hit is not None else (vals[:3] or message.get("text", "")[:80]))
    if "rows" in expect:
        for m in row_maps(blocks):
            if all(str(k) in m and any(close(v, float(want), tol) for v in m[str(k)]) for k, want in expect["rows"].items()):
                return True, f"{len(m)} rows"
        return False, json.dumps([dict(list(m.items())[:3]) for m in row_maps(blocks)], default=str)[:120] or message.get("text", "")[:80]
    if "total" in expect:
        totals = [b["total"] for b in blocks if b["type"] == "table" and b.get("selection_id")]
        if expect.get("intent") == "rows" and not totals:
            return False, "no row list"
        totals = totals or [b.get("total") for b in blocks if b["type"] == "table"]
        return expect["total"] in totals, str(totals)
    return False, "no expectation"


def unsourced(message: dict) -> bool:
    shows_data = any(b["type"] in ("number", "table", "chart") for b in message.get("blocks") or [])
    return shows_data and not any(s.get("sql") for s in message.get("sources") or [])


def ask(client, ds_id: str, text: str) -> dict:
    with client.stream("POST", f"{API}/datasets/{ds_id}/chat", json={"text": text, "context": {"tab": "dashboard"}}) as r:
        event = None
        for line in r.iter_lines():
            if line.startswith("event: "):
                event = line[7:]
            elif line.startswith("data: ") and event == "message":
                return json.loads(line[6:])
    return {"blocks": [], "sources": [], "text": "(no answer)"}


def ready(client, filename: str, timeout_s: float = 600) -> str:
    path = SAMPLES / filename
    ds = client.post(f"{API}/datasets", files={"file": (path.name, path.read_bytes(), "text/csv")}).json()
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        status = client.get(f"{API}/datasets/{ds['id']}").json()["status"]
        if status == "offer":
            client.post(f"{API}/datasets/{ds['id']}/use-as-is")
        elif status in ("ready", "failed"):
            return ds["id"]
        time.sleep(0.5)
    raise TimeoutError(f"{filename} didn't become ready")


def evaluate(client, questions: dict[str, list[dict]], only: list[str] | None = None) -> list[Outcome]:
    out = []
    for filename, items in questions.items():
        if only and filename not in only:
            continue
        ds_id = ready(client, filename)
        for item in items:
            t0 = time.monotonic()
            message = ask(client, ds_id, item["q"])
            ok, got = check(message, item["expect"])
            out.append(Outcome(filename, item["q"], ok, got, json.dumps(item["expect"]), time.monotonic() - t0,
                               unsourced(message)))
    return out


def report(outcomes: list[Outcome]) -> str:
    lines = ["| File | Question | Pass | Got | Seconds |", "|---|---|---|---|---|"]
    for o in outcomes:
        lines.append(f"| {o.dataset} | {o.question} | {'yes' if o.ok else 'NO'} | {o.got[:60].replace('|', '/')} | {o.seconds:.1f} |")
    passed = sum(o.ok for o in outcomes)
    secs = sorted(o.seconds for o in outcomes)
    median = secs[len(secs) // 2] if secs else 0
    lines += ["", f"Passed {passed} of {len(outcomes)}. Unsourced answers: {sum(o.unsourced for o in outcomes)}. "
                  f"Median {median:.1f} s per answer."]
    return "\n".join(lines)


def run(only: list[str] | None = None) -> str:
    from fastapi.testclient import TestClient

    from sherlock.config import get_settings
    from sherlock.main import create_app

    with tempfile.TemporaryDirectory(prefix="sherlock-eval-") as tmp:
        os.environ["DATA_DIR"] = tmp
        os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmp, 'sherlock.db').as_posix()}"
        os.environ.setdefault("JOB_WORKERS", "2")
        get_settings.cache_clear()
        with TestClient(create_app()) as client:
            outcomes = evaluate(client, load(), only)
        get_settings.cache_clear()
    return report(outcomes)
