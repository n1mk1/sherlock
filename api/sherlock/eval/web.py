"""The web eval (TRD §14): `samples/eval/web_questions.yaml`, ten outside-world questions and ten
column-meaning questions over the three eval files, asked through `POST /chat` as the ask eval does.

Each question is asked three times, with web retrieval on, failing and off:
- **on:** the answer cites a web source with a URL and shows the web block; the model's web prose has no
  digits, numbers in words or causal wording; a column-meaning answer still has its query source.
- **failing:** Tavily answers a 502 or times out (alternately). The answer still comes, with the one-line
  note, and a column-meaning answer keeps its data and the model's general block.
- **off:** no key. An outside-world question gets the one line; a column-meaning answer is exactly what it
  was before web retrieval (a query source and a general block, no web source and no note).

Across every pass, every outbound request is captured (the privacy assertion): none may hold a cell value
of the file, or a digit run, that the question doesn't hold. This checks every cell of the file, not only
the value index the agent's own check uses. It reports p50 latency per answer and per Tavily call.

Modes:
- offline (default): Nemotron's replies from `samples/eval/web/llm.json` (`LLM_MOCK`) and Tavily's from
  `samples/eval/web/tavily.json`, with no network. Deterministic.
- `--live`: real Nemotron and real Tavily (needs `TAVILY_API_KEY`); run it through `eval-locked.sh`.
- `--record`: real Nemotron with the recorded Tavily responses; rewrites `llm.json` (to refresh the fixtures).
"""

import json
import os
import re
import statistics
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import yaml

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
QUESTIONS = SAMPLES / "eval" / "web_questions.yaml"
FIXTURES = SAMPLES / "eval" / "web"
API = "/api/v1"
PASSES = ("on", "failing", "off")
WORD = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*", re.UNICODE)
DIGITS = re.compile(r"\d+")
GENERIC = frozenset("a an the and or of to in on for with is are be it this that how do does what which why who "
                    "other others none unknown yes no true false null nan missing n/a na all any total".split())


@dataclass
class Outcome:
    dataset: str
    question: str
    kind: str          # outside | meaning
    run: str           # on | failing | off
    ok: bool
    why: str
    seconds: float
    leaks: list[str] = field(default_factory=list)


def load(path: Path = QUESTIONS) -> dict[str, list[dict]]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# --- what went out ------------------------------------------------------------------------------------

def cell_values(path: Path) -> tuple[list[str], set[str]]:
    """The file's column names and every distinct cell value, as text."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    values = set()
    for col in df.columns:
        values.update(v.strip() for v in df[col].unique() if v and v.strip())
    return list(df.columns), values


def leaks(request: dict, question: str, columns: list[str], values: set[str]) -> list[str]:
    """Cell values and digit runs in an outbound request that the question and the column names don't hold.
    Written apart from `agent/web.py::check_query` (which reads the value index), so it checks that check."""
    # What a caller chose (the query, the URLs, the instructions); the fixed parameters are the client's own.
    text = " ".join(v if isinstance(v, str) else json.dumps(v) for k, v in request.items() if k in ("query", "urls", "url", "instructions"))
    said = question + " " + " ".join(columns)
    out = [f"digits {d}" for d in DIGITS.findall(text) if d not in DIGITS.findall(said)]
    q = [t.lower() for t in WORD.findall(text)]
    grams = {" ".join(q[i:i + n]) for n in range(1, 9) for i in range(len(q) - n + 1)}
    allowed = " " + " ".join(t.lower() for t in WORD.findall(said)) + " "
    for v in values:
        words = [t.lower() for t in WORD.findall(v)]
        keys = [" ".join(words)] + [" ".join(words[i:i + 2]) for i in range(len(words) - 1)]  # the value, or two of its words
        for key in keys:
            if len(key) < 3 or all(w in GENERIC or w.isdigit() for w in key.split()) or f" {key} " in allowed:
                continue
            if key in grams:
                out.append(v)
                break
    return out


# --- the answer ---------------------------------------------------------------------------------------

def ask(client, ds_id: str, text: str, tries: int = 6) -> tuple[dict | None, list[str]]:
    """One question through `POST /chat`: the final message and the error events, if any."""
    for _ in range(tries):
        errors: list[str] = []
        with client.stream("POST", f"{API}/datasets/{ds_id}/chat", json={"text": text, "context": {"tab": "csv"}}) as r:
            if r.status_code == 429:
                time.sleep(float(r.headers.get("retry-after") or 6))
                continue
            event, message = None, None
            for line in r.iter_lines():
                if line.startswith("event: "):
                    event = line[7:]
                elif line.startswith("data: ") and event == "message":
                    message = json.loads(line[6:])
                elif line.startswith("data: ") and event == "error":
                    errors.append(json.loads(line[6:]).get("message", "error"))
            return message, errors
    return None, ["rate limited"]


def web_prose(message: dict) -> list[str]:
    """The model-written text runs of the answer's web blocks (the code's lead line left out)."""
    from sherlock.agent.web import WEB_LEAD

    out = []
    for b in message.get("blocks") or []:
        if b.get("type") == "text" and b.get("labeled") == "web":
            for para in b["body"]["blocks"]:
                out += [r["text"] for r in para["runs"] if r["type"] == "text" and not r["text"].startswith(("From the web", "In general, from the web"))]
    return [t for t in out if t != WEB_LEAD]


def wording(texts: list[str]) -> str | None:
    from sherlock.llm.text import has_digits
    from sherlock.llm.wording import CAUSAL, number_in_words

    for t in texts:
        if has_digits(t):
            return f"digits in web prose: {t[:60]!r}"
        if number_in_words(t):
            return f"a number in words in web prose: {t[:60]!r}"
        if CAUSAL.search(t):
            return f"causal wording in web prose: {t[:60]!r}"
    return None


def check(message: dict | None, errors: list[str], kind: str, run: str) -> tuple[bool, str]:
    from sherlock.web.client import NOTES

    if message is None or errors:
        return False, "no answer" if message is None else f"error event: {errors[0]}"
    kinds = [s.get("kind") for s in message.get("sources") or []]
    web = [s for s in message.get("sources") or [] if s.get("kind") == "web"]
    text = message.get("text") or ""
    has_note = any(n in text for n in NOTES.values())
    if run == "on":
        if not web or not all(str(s.get("url", "")).startswith(("http://", "https://")) for s in web):
            return False, f"no web source with a URL ({', '.join(map(str, kinds)) or 'no sources'}): {text[:60]}"
        if not any(b.get("type") == "web_sources" for b in message["blocks"]):
            return False, "no sources list"
        if kind == "meaning" and "sql" not in kinds:
            return False, "no query behind the data part"
        bad = wording(web_prose(message))
        return (False, bad) if bad else (True, f"{len(web)} web sources")
    if run == "failing":
        if web:
            return False, "a web source while Tavily failed"
        if not has_note:
            return False, f"no one-line note: {text[:60]}"
        if kind == "meaning" and "sql" not in kinds:
            return False, f"the data part is missing ({', '.join(map(str, kinds))})"
        return True, "fails soft" if kind == "outside" or "general" in kinds else "fails soft (the model wrote no general sentence)"
    # off: today's behaviour
    if web:
        return False, "a web source with no key"
    if kind == "outside":
        return (True, "one line") if NOTES["off"] in text else (False, f"not the off line: {text[:60]}")
    # Today's answer: the data part and, when the model wrote one, the general sentence (it sometimes writes none,
    # with or without the web: the meaning call's own variance), never a web part or a note.
    if "sql" not in kinds or set(kinds) - {"sql", "general"} or has_note:
        return False, f"not today's answer ({', '.join(map(str, kinds))}{', with a note' if has_note else ''})"
    return True, "unchanged" if "general" in kinds else "unchanged (the model wrote no general sentence)"


# --- the run ------------------------------------------------------------------------------------------

def ready(client, filename: str, timeout_s: float = 300) -> str:
    path = SAMPLES / filename
    for _ in range(10):  # a 429 (60 uploads and messages a minute per user, TRD §15) waits its Retry-After
        r = client.post(f"{API}/datasets", files={"file": (path.name, path.read_bytes(), "text/csv")})
        if r.status_code != 429:
            break
        time.sleep(float(r.headers.get("retry-after") or 6))
    ds = r.json()
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        status = client.get(f"{API}/datasets/{ds['id']}").json()["status"]
        if status in ("offer", "ready"):
            return ds["id"]
        if status == "failed":
            raise RuntimeError(f"{filename} failed to import")
        time.sleep(0.3)
    raise TimeoutError(f"{filename} didn't finish profiling")


class Capture:
    """Wraps the pass's transport and keeps every request it was asked to send."""

    def __init__(self, inner) -> None:
        self.inner, self.calls = inner, []

    def call(self, kind, params, timeout):
        self.calls.append(params)
        return self.inner.call(kind, params, timeout)


def evaluate(client, questions: dict[str, list[dict]], mode: str, only: list[str] | None = None) -> tuple[list[Outcome], list[int]]:
    from sherlock.config import get_settings
    from sherlock.db.connection import connect
    from sherlock.web import client as web_client
    from sherlock.web.fixtures import FailingTransport, WebFixtureTransport

    outcomes: list[Outcome] = []
    real = web_client.make_transport
    on = (web_client.TavilyTransport(get_settings().tavily_api_key) if mode == "live"
          else WebFixtureTransport.load(FIXTURES / "tavily.json"))
    try:
        for filename, items in questions.items():
            if only and filename not in only:
                continue
            columns, values = cell_values(SAMPLES / filename)
            for run in PASSES:
                ds_id = ready(client, filename)  # a fresh thread per pass, so a pass can't lean on the last
                db = connect(get_settings())
                db.execute("DELETE FROM web_cache")  # each pass asks Tavily (or its stand-in) itself
                db.close()
                for i, item in enumerate(items):
                    inner = on if run == "on" else FailingTransport("timeout" if i % 2 else "failed") if run == "failing" else None
                    cap = Capture(inner) if inner is not None else None
                    web_client.make_transport = lambda settings, cap=cap: cap
                    os.environ["CURRENT_QUESTION"] = item["q"]
                    t0 = time.monotonic()
                    message, errors = ask(client, ds_id, item["q"])
                    ok, why = check(message, errors, item["kind"], run)
                    leaked = [v for req in (cap.calls if cap else []) for v in leaks(req, item["q"], columns, values)]
                    if leaked:
                        ok, why = False, f"sent {leaked[0]!r}"
                    outcomes.append(Outcome(filename, item["q"], item["kind"], run, ok, why, time.monotonic() - t0, leaked))
    finally:
        web_client.make_transport = real
    db = connect(get_settings())
    web_ms = [r[0] for r in db.execute("SELECT latency_ms FROM llm_calls WHERE role = 'web' AND cached = 0 AND ok = 1")]
    db.close()
    return outcomes, web_ms


def passed(outcomes: list[Outcome]) -> bool:
    """The eval's verdict: nothing from the file went out, and no answer, with the web on, failing or off, ended in
    an error. Each pass's score is reported beside it (a routing miss lowers it but isn't a failure of the web)."""
    return not any(o.leaks or o.why.startswith(("error event", "no answer")) for o in outcomes)


def report(outcomes: list[Outcome], web_ms: list[int], mode: str) -> str:
    lines = ["| File | Question | Kind | Web | Pass | Why | Seconds |", "|---|---|---|---|---|---|---|"]
    for o in outcomes:
        lines.append(f"| {o.dataset} | {o.question} | {o.kind} | {o.run} | {'yes' if o.ok else 'NO'} | "
                     f"{o.why[:70].replace('|', '/')} | {o.seconds:.1f} |")
    lines.append("")
    for run in PASSES:
        part = [o for o in outcomes if o.run == run]
        if part:
            secs = [o.seconds for o in part]
            lines.append(f"Web {run}: {sum(o.ok for o in part)} of {len(part)} passed, median {statistics.median(secs):.1f} s per answer.")
    leaked = sum(len(o.leaks) for o in outcomes)
    lines.append(f"Outbound requests holding a cell value: {leaked}.")
    broken = [o for o in outcomes if o.why.startswith(("error event", "no answer"))]
    lines.append(f"Privacy assertion: {'passed' if not leaked else 'FAILED'}. "
                 f"Fail-soft: {'no answer ended in an error' if not broken else f'{len(broken)} answers ended in an error (FAILED)'}.")
    if web_ms:
        lines.append(f"Tavily calls: {len(web_ms)}, p50 {statistics.median(web_ms):.0f} ms ({mode}).")
    return "\n".join(lines)


def run(only: list[str] | None = None, mode: str = "offline") -> tuple[str, bool]:
    """`mode`: offline (recorded Nemotron and Tavily), live (both real) or record (real Nemotron, recorded Tavily,
    rewriting the Nemotron fixtures)."""
    from fastapi.testclient import TestClient

    from sherlock import ratelimit
    from sherlock.config import get_settings
    from sherlock.main import create_app

    if mode == "live" and not os.environ.get("TAVILY_API_KEY") and not get_settings().tavily_api_key:
        return "`sherlock eval web --live` needs TAVILY_API_KEY (in .env or the environment). The offline run needs none.", False
    recorded = FIXTURES / "llm.json"
    with tempfile.TemporaryDirectory(prefix="sherlock-eval-web-") as tmp:
        os.environ["DATA_DIR"] = tmp
        os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmp, 'sherlock.db').as_posix()}"
        os.environ.setdefault("JOB_WORKERS", "2")
        os.environ["WEB_RATE_LIMIT"] = "0"   # three passes over twenty questions in a few minutes
        os.environ["WEB_SEARCH"] = "on"
        if mode == "offline":
            os.environ["LLM_MOCK"] = str(recorded)
            ratelimit.LIMITS_PER_MINUTE["llm"] = 10_000  # no model behind it: nothing to protect
            ratelimit.LIMITS_PER_MINUTE["mutate"] = 10_000
        entries: list[dict] = []
        if mode == "record":
            os.environ["LLM_RECORD"] = str(Path(tmp, "unused.json"))
            _record_into(entries)
        get_settings.cache_clear()
        with TestClient(create_app()) as client:
            outcomes, web_ms = evaluate(client, load(), mode, only)
        get_settings.cache_clear()
    if mode == "record":
        recorded.write_text(json.dumps(entries, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return report(outcomes, web_ms, mode), passed(outcomes)


def _record_into(entries: list[dict]) -> None:
    """Make `LLM_RECORD` keep each live reply with what identifies its question, so the offline run gives every
    question its own replies: the question's own data block when the prompt holds it (the recent messages quote
    earlier questions too, so the bare question would match them), else the column a meaning prompt is about."""
    from sherlock.llm import fixtures

    class Recorder(fixtures.Transport):
        def __init__(self, inner, path) -> None:
            self.inner = inner

        def create(self, *, model, messages, timeout, purpose, **kwargs) -> dict:
            out = self.inner.create(model=model, messages=messages, timeout=timeout, purpose=purpose, **kwargs)
            prompt = "\n".join(str(m.get("content") or "") for m in messages)
            q = os.environ.get("CURRENT_QUESTION", "")
            col = re.search(r"^column: (.+)$", prompt, re.M)
            own = f"<data>\n{q}\n</data>"  # the message's own block: a prompt also quotes earlier questions
            match = [own] if q and own in prompt else [f"column: {col.group(1)}"] if col else []
            entries.append({"purpose": purpose, "match": match, "content": out["content"],
                            "prompt_tokens": out.get("prompt_tokens"), "completion_tokens": out.get("completion_tokens"),
                            "finish_reason": out.get("finish_reason", "stop")})
            return out

    fixtures.RecordingTransport = Recorder
