"""The corruption benchmark (Implementation Plan D3.3, TRD §14): damage clean data in known ways,
run the Cleaner, and score what came back.

For each clean set, seeded injectors damage cells and remember each one's clean value. The damaged
CSV goes through the real pipeline in-process (import → profile and typing → Cleaner → the final
version), with the real model unless `LLM_MOCK` is set. Scores per set:
- recovery: damaged cells whose final value equals the clean value
- wrong: damaged cells changed into a value that isn't the clean one (a guess that missed, such as
  a date read in the wrong order); a damaged cell left as it was, or emptied with its row
  quarantined, isn't wrong, only not recovered
- harm: undamaged cells whose final value no longer equals the clean value
- row loss: rows missing from the final version (must be 0); quarantined rows are counted apart

The output ends with every step the Cleaner committed (its gate and confidence) and every issue it
skipped and why, so a fix that didn't happen can be told from one that went wrong.

Three sets test what the Cleaner must not do (plan 2.6): `dates_dmy` and `dates_mdy` hold the same
kind of column, dates whose every day is 12 or less, written day-first in one and month-first in
the other, so nothing in the data tells them apart and any fixed guess is wrong on one of them; and
`lookalikes` holds categories that look alike but are different ("Plan A"/"Plan B", "Region 1"/
"Region 2", "Austria"/"Australia"), so a merge is harm. `dates_dmy_picked` and `dates_mdy_picked` are
the two date sets cleaned through a plan in which the user picked the right order (plan 2b.9).
"""

import io
import math
import os
import random
import re
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from sherlock.eval import synthetic

SAMPLE = Path(__file__).resolve().parents[2] / "samples" / "titanic3.csv"


@dataclass
class Damage:
    row: int
    column: str
    kind: str
    clean: object
    missing_ok: bool = False  # a placeholder's honest recovery is a missing value (or the original)


@dataclass
class Case:
    name: str
    clean: pd.DataFrame
    dirty: pd.DataFrame
    damage: list[Damage] = field(default_factory=list)
    date_order: str | None = None  # clean through a plan with this order picked for its ambiguous dates


def _cells(df: pd.DataFrame, column: str, share: float, rng: random.Random, taken: set) -> list[int]:
    rows = [i for i in range(len(df)) if (i, column) not in taken and pd.notna(df.at[i, column])]
    picked = rng.sample(rows, max(1, int(len(rows) * share)))
    taken.update((i, column) for i in picked)
    return picked


def money(value) -> str:
    """Currency formatting that keeps every digit, so the clean value is recoverable."""
    return f"${float(value):,}".replace(".0", "") if float(value).is_integer() else f"${float(value):,}"


def case_variant(value: str, rng: random.Random) -> str:
    return rng.choice([value.lower(), value.upper(), f" {value}", f"{value}  ", value.swapcase()])


def typo(value: str, rng: random.Random) -> str:
    if len(value) < 5:
        return value.lower()
    i = rng.randrange(1, len(value) - 1)
    return value[:i] + value[i + 1:]  # drop one letter: "Southampton" → "Southmpton"


def mojibake(value: str) -> str:
    return value.encode("utf-8").decode("latin-1", errors="replace")


def corrupt(name: str, clean: pd.DataFrame, plan: list[tuple[str, str, float]], seed: int) -> Case:
    """plan: [(column, kind, share)], kinds: money, sentinel, case, typo, mojibake, dmy_date (an
    unambiguous day-first date), dmy_text and mdy_text (any date written day-first or month-first)."""
    rng = random.Random(seed)
    dirty = clean.astype(object).copy()
    case = Case(name, clean, dirty)
    taken: set = set()
    for column, kind, share in plan:
        for i in _cells(clean, column, share, rng, taken):
            value = clean.at[i, column]
            if kind == "money":
                new = money(value)
            elif kind == "sentinel":
                new = rng.choice(["N/A", "-999", "?"])
            elif kind == "case":
                new = case_variant(str(value), rng)
            elif kind == "typo":
                new = typo(str(value), rng)
            elif kind == "mojibake":
                new = mojibake(str(value))
                if new == value:
                    continue
            elif kind == "dmy_date":
                d = pd.Timestamp(value)
                if d.day <= 12:
                    continue  # keep it unambiguous
                new = d.strftime("%d/%m/%Y")
            elif kind in ("dmy_text", "mdy_text"):
                new = pd.Timestamp(value).strftime("%d/%m/%Y" if kind == "dmy_text" else "%m/%d/%Y")
            else:
                raise ValueError(kind)
            dirty.at[i, column] = new
            case.damage.append(Damage(i, column, kind, value, missing_ok=kind == "sentinel"))
    return case


def cases() -> list[Case]:
    titanic = synthetic.titanic_clean(SAMPLE)
    sales = synthetic.sales(rows=1500)
    hr = synthetic.hr(rows=800)
    visits = synthetic.visits(rows=400)
    return [
        corrupt("titanic_clean", titanic, [("fare", "money", 0.3), ("embarked", "case", 0.15), ("age", "sentinel", 0.04)], 1),
        corrupt("sales", sales, [("unit_price", "money", 0.25), ("region", "case", 0.2), ("product", "typo", 0.03),
                                 ("units", "sentinel", 0.03)], 2),
        corrupt("hr", hr, [("department", "case", 0.15), ("city", "mojibake", 0.08), ("hire_date", "dmy_date", 0.2),
                           ("salary", "sentinel", 0.02)], 3),
        corrupt("dates_dmy", visits, [("visit_date", "dmy_text", 1.0)], 4),
        corrupt("dates_mdy", visits, [("visit_date", "mdy_text", 1.0)], 5),
        corrupt("lookalikes", synthetic.lookalikes(rows=600), [("plan", "case", 0.1), ("region", "case", 0.1),
                                                                ("country", "case", 0.08), ("monthly_fee", "money", 0.2)], 6),
        picked(corrupt("dates_dmy_picked", visits, [("visit_date", "dmy_text", 1.0)], 4), "dmy"),
        picked(corrupt("dates_mdy_picked", visits, [("visit_date", "mdy_text", 1.0)], 5), "mdy"),
    ]


def picked(case: Case, order: str) -> Case:
    case.date_order = order
    return case


ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}([ T].*)?$")
BOOL_WORDS = {"true": True, "t": True, "yes": True, "y": True, "false": False, "f": False, "no": False, "n": False}


def _as_bool(v):
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    return BOOL_WORDS.get(v.strip().lower()) if isinstance(v, str) else None


def same(a, b) -> bool:
    """Equal as values: numbers within 1e-6, dates by day, yes/no text equal to booleans (the typing
    step casts such columns), otherwise exact text. Two texts are compared as dates only when both
    are ISO (`2021-04-03`): reading "04/03/2021" as a date would pick an order for it, so a date the
    Cleaner left as text never counts as recovered."""
    if (a is None or (isinstance(a, float) and math.isnan(a))) and (b is None or (isinstance(b, float) and math.isnan(b))):
        return True
    if a is None or b is None or (isinstance(a, float) and math.isnan(a)) or (isinstance(b, float) and math.isnan(b)):
        return False
    ba, bb = _as_bool(a), _as_bool(b)
    if ba is not None and bb is not None:
        return ba == bb
    try:
        return math.isclose(float(a), float(b), rel_tol=1e-6, abs_tol=1e-6)
    except (TypeError, ValueError):
        pass
    if isinstance(a, str) and isinstance(b, str) and not (ISO_DATE.match(a) and ISO_DATE.match(b)):
        return a == b
    try:
        return pd.Timestamp(a).normalize() == pd.Timestamp(b).normalize() and not str(a).isalpha()
    except (TypeError, ValueError):
        pass
    return str(a) == str(b)


def changed(got, dirty) -> bool:
    """The final value isn't the damaged one any more. An emptied value counts as unchanged (its row
    was quarantined or its placeholder cleared, which isn't a guess), and so does the same number
    typed ("-999" → -999.0); a date parsed from text has changed, whichever order it was read in."""
    if got is None or (isinstance(got, float) and math.isnan(got)):
        return False
    if isinstance(got, str):
        return got != dirty
    try:
        return not math.isclose(float(got), float(dirty), rel_tol=1e-6, abs_tol=1e-6)
    except (TypeError, ValueError):
        return True


@dataclass
class Score:
    name: str
    damaged: int
    recovered: int
    wrong: int
    harmed: int
    undamaged: int
    rows_in: int
    rows_out: int
    quarantined: int
    steps: int
    seconds: float
    ended_by: str
    by_kind: dict = field(default_factory=dict)  # "column: kind" → [recovered, damaged, wrong]
    skipped: list = field(default_factory=list)  # the report's skipped issues: (column, detector, reason)
    committed: list = field(default_factory=list)  # the report's steps: (summary, gate, confidence)

    def row(self) -> str:
        rec = self.recovered / self.damaged if self.damaged else 1.0
        harm = self.harmed / self.undamaged if self.undamaged else 0.0
        loss = (self.rows_in - self.rows_out) / self.rows_in if self.rows_in else 0.0
        wrong = self.wrong / self.damaged if self.damaged else 0.0
        return (f"| {self.name} | {self.rows_in:,} | {self.damaged:,} | {rec:.1%} | {wrong:.1%} | {harm:.2%} | "
                f"{loss:.1%} | {self.quarantined} | {self.steps} | {self.seconds:.0f} s | {self.ended_by} |")


HEADER = ("| Set | Rows | Damaged cells | Recovered | Wrong | Harm | Row loss | Quarantined | Steps | Time | Ended by |\n"
          "|---|---|---|---|---|---|---|---|---|---|---|")


def score(case: Case, final: pd.DataFrame, steps: int, seconds: float, ended_by: str) -> Score:
    final = final.sort_values("_row_id").set_index("_row_id")
    damaged = {(d.row, d.column): d for d in case.damage}
    recovered = wrong = harmed = undamaged = 0
    by_kind: dict = {}
    for i in range(len(case.clean)):
        rid = i + 1
        if rid not in final.index:
            continue
        for col in case.clean.columns:
            got = final.at[rid, col] if col in final.columns else None
            got = None if (got is not None and not isinstance(got, str) and pd.isna(got)) else got
            if (i, col) in damaged:
                kind = by_kind.setdefault(f"{col}: {damaged[(i, col)].kind}", [0, 0, 0])
                kind[1] += 1
                d = damaged[(i, col)]
                if same(got, d.clean) or (d.missing_ok and got is None):
                    recovered += 1
                    kind[0] += 1
                elif changed(got, case.dirty.at[i, col]):
                    wrong += 1
                    kind[2] += 1
            else:
                undamaged += 1
                if not same(got, case.clean.at[i, col]):
                    harmed += 1
    return Score(case.name, len(case.damage), recovered, wrong, harmed, undamaged, len(case.clean), len(final),
                 int(final["_quarantine_reason"].notna().sum()), steps, seconds, ended_by, by_kind)


def run_case(client, case: Case, timeout_s: float = 900) -> Score:
    api = "/api/v1"
    buf = io.StringIO()
    case.dirty.to_csv(buf, index=False)
    r = client.post(f"{api}/datasets", files={"file": (f"{case.name}.csv", buf.getvalue().encode(), "text/csv")})
    r.raise_for_status()
    ds_id = r.json()["id"]
    started = time.monotonic()
    _wait(lambda: client.get(f"{api}/datasets/{ds_id}").json()["status"] in ("offer", "failed"), timeout_s)
    body = {}
    if case.date_order:  # the user picks the order of the ambiguous dates in the plan, then starts it
        plan = client.post(f"{api}/datasets/{ds_id}/clean/plan", json={}).json()
        ops = [{"op": "set_date_order", "item_id": i["id"], "order": case.date_order}
               for i in plan["items"] if "date_order" in i]
        client.patch(f"{api}/clean-plans/{plan['id']}", json={"ops": ops}).raise_for_status()
        body = {"plan_id": plan["id"]}
    job = client.post(f"{api}/datasets/{ds_id}/clean", json=body).json()
    _wait(lambda: client.get(f"{api}/jobs/{job['id']}").json()["status"] in ("done", "failed", "cancelled"), timeout_s)
    report = client.get(f"{api}/datasets/{ds_id}/report").json()
    final = _final(client, ds_id)
    result = score(case, final, len(report["steps"]), time.monotonic() - started, report["ended_by"])
    result.skipped = [(s["column"], s["detector"], s["reason"]) for s in report["skipped"]]
    result.committed = [(s["summary"], s["gate"], s["confidence"]) for s in report["steps"]]
    return result


def _final(client, ds_id: str) -> pd.DataFrame:
    from sherlock.config import get_settings
    from sherlock.db.connection import connect
    from sherlock.storage import dataset_dir, sql_path

    db = connect(get_settings())
    try:
        d = db.execute("SELECT * FROM datasets WHERE id = ?", (ds_id,)).fetchone()
        v = db.execute("SELECT parquet_path FROM versions WHERE dataset_id = ? AND version = ?",
                       (ds_id, d["current_version"])).fetchone()
        path = dataset_dir(get_settings(), d["user_id"], ds_id) / v["parquet_path"]
    finally:
        db.close()
    conn = duckdb.connect()
    try:
        return conn.execute(f"SELECT * FROM read_parquet({sql_path(path)})").df()
    finally:
        conn.close()


def _wait(fn, timeout_s: float) -> None:
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if fn():
            return
        time.sleep(1)
    raise TimeoutError("the benchmark timed out waiting for a job")


def run(names: list[str] | None = None) -> str:
    """Run the benchmark in a throwaway data directory and return the markdown table."""
    from fastapi.testclient import TestClient

    from sherlock.config import get_settings
    from sherlock.main import create_app

    with tempfile.TemporaryDirectory(prefix="sherlock-eval-") as tmp:
        os.environ["DATA_DIR"] = tmp
        os.environ["DATABASE_URL"] = f"sqlite:///{Path(tmp, 'sherlock.db').as_posix()}"
        os.environ.setdefault("JOB_WORKERS", "2")
        get_settings.cache_clear()
        lines = [HEADER]
        details = ["", "| Set | Damage | Recovered | Wrong |", "|---|---|---|---|"]
        skips = ["", "| Set | Skipped | Reason |", "|---|---|---|"]
        steps = ["", "| Set | Step | Gate | Confidence |", "|---|---|---|---|"]
        with TestClient(create_app()) as client:
            for case in cases():
                if names and case.name not in names:
                    continue
                result = run_case(client, case)
                lines.append(result.row())
                details += [f"| {case.name} | {k} | {r}/{n} | {w} |" for k, (r, n, w) in sorted(result.by_kind.items())]
                skips += [f"| {case.name} | {d} in {c or 'rows'} | {why.replace('|', '/')} |" for c, d, why in result.skipped]
                steps += [f"| {case.name} | {name.replace('|', '/')} | {g} | {'—' if conf is None else f'{conf:.2f}'} |"
                          for name, g, conf in result.committed]
        get_settings.cache_clear()
    return "\n".join(lines + details + steps + skips)
