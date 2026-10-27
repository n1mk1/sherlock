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

Three checks of the severity review and the report (PRD CLEAN-8c, CLEAN-6), per set:
- ratings: each damage the model rated (`issue_reviews`, `sev_source` model) is at least as severe as its
  detector's own default level when its column is the target or a measure (the floor, TRD §7.2), and
  `splits` or below on free text; "—" when nothing was rated (recorded replies, or the review off)
- report honest: the report's "couldn't fix" and "checked and kept" equal the skips read from their
  reasons, so the counts aren't the classifier marking its own homework
- stable: reviewing the same version again gives the same levels

Three sets test what the Cleaner must not do: `dates_dmy` and `dates_mdy` hold the same
kind of column, dates whose every day is 12 or less, written day-first in one and month-first in
the other, so nothing in the data tells them apart and any fixed guess is wrong on one of them; and
`lookalikes` holds categories that look alike but are different ("Plan A"/"Plan B", "Region 1"/
"Region 2", "Austria"/"Australia"), so a merge is harm. `dates_dmy_picked` and `dates_mdy_picked` are
the two date sets cleaned through a plan in which the user picked the right order.
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


def corrupt(name: str, clean: pd.DataFrame, plan: list[tuple[str, str, float]], seed: int) -> Case:
    """plan: [(column, damage, share)]. A damage is a detector's damage kind from the registry,
    "<detector>" for its first kind or "<detector>:<kind>" (TRD §14), so a new detector's damage needs
    no eval code: numbers_as_text (money), sentinels, whitespace_case (case), near_duplicate_categories
    (typo), mojibake, mixed_types:dmy_date (an unambiguous day-first date), ambiguous_dates:dmy_text and
    ambiguous_dates:mdy_text (any date written day-first or month-first), and the others' own kinds."""
    from sherlock.cleaning import registry

    rng = random.Random(seed)
    dirty = clean.astype(object).copy()
    case = Case(name, clean, dirty)
    taken: set = set()
    for column, damage, share in plan:
        injector = registry.injector(damage)
        rows = _cells(clean, column, share, rng, taken)
        for (i, c), new in injector.damage(clean, column, rows, rng).items():
            dirty.at[i, c] = new
            case.damage.append(Damage(i, c, damage, clean.at[i, c], missing_ok=injector.missing_ok))
    return case


def cases() -> list[Case]:
    titanic = synthetic.titanic_clean(SAMPLE)
    sales = synthetic.sales(rows=1500)
    hr = synthetic.hr(rows=800)
    visits = synthetic.visits(rows=400)
    return [
        corrupt("titanic_clean", titanic, [("fare", "numbers_as_text", 0.3), ("embarked", "whitespace_case", 0.15),
                                           ("age", "sentinels", 0.04)], 1),
        corrupt("sales", sales, [("unit_price", "numbers_as_text", 0.25), ("region", "whitespace_case", 0.2),
                                 ("product", "near_duplicate_categories", 0.03), ("units", "sentinels", 0.03)], 2),
        corrupt("hr", hr, [("department", "whitespace_case", 0.15), ("city", "mojibake", 0.08),
                           ("hire_date", "mixed_types:dmy_date", 0.2), ("salary", "sentinels", 0.02)], 3),
        corrupt("dates_dmy", visits, [("visit_date", "ambiguous_dates:dmy_text", 1.0)], 4),
        corrupt("dates_mdy", visits, [("visit_date", "ambiguous_dates:mdy_text", 1.0)], 5),
        corrupt("lookalikes", synthetic.lookalikes(rows=600), [("plan", "whitespace_case", 0.1), ("region", "whitespace_case", 0.1),
                                                                ("country", "whitespace_case", 0.08),
                                                                ("monthly_fee", "numbers_as_text", 0.2)], 6),
        picked(corrupt("dates_dmy_picked", visits, [("visit_date", "ambiguous_dates:dmy_text", 1.0)], 4), "dmy"),
        picked(corrupt("dates_mdy_picked", visits, [("visit_date", "ambiguous_dates:mdy_text", 1.0)], 5), "mdy"),
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
    ratings: list = field(default_factory=list)  # (column, damage, level, as expected), for model-rated damage
    honest: bool | None = None                    # the report's lines agree with the skip reasons
    stable: bool | None = None                    # a second review of the version gave the same levels
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
    result.honest = honest(report)
    result.ratings, result.stable = _review_checks(client, ds_id, case, report["from_version"], timeout_s)
    return result


FREE_TEXT = {"splits", "check", "cosmetic"}
FAILED = ("No candidate passed", "Failed", "Skipped:", "model output invalid", "Not applied", "The fix changed nothing",
          "The data changed")


def honest(report: dict) -> bool | None:
    """The report's "couldn't fix" and "checked and kept" against the skips' own reasons (PRD CLEAN-6);
    None for a report without those counts."""
    counts = report["counts"]
    if "couldnt_fix" not in counts:
        return None
    reasons = [s["reason"] for s in report["skipped"]]
    failed = sum(1 for r in reasons if r.startswith(FAILED))
    kept = sum(1 for r in reasons if r.startswith("Left as is"))
    return counts["couldnt_fix"] == failed and counts["checked_and_kept"] == kept


def expected(role: str, level: str, default: str | None) -> bool | None:
    """Whether a rated level fits the column's role, or None when the role sets no expectation: on the
    target or a measure, at least as severe as the detector's default (the floor); on free text, splits
    or below."""
    from sherlock.cleaning.levels import rank

    if role in ("target", "measure") and default:
        return rank(level) <= rank(default)
    return level in FREE_TEXT if role == "free_text" else None


def _review_checks(client, ds_id: str, case: Case, version: int | None, timeout_s: float) -> tuple[list, bool | None]:
    from sherlock.cleaning import levels, registry, review
    from sherlock.config import get_settings
    from sherlock.db.connection import connect
    from sherlock.llm.client import CallScope
    from sherlock.profile import service as profile_service

    api = "/api/v1"
    _wait(lambda: not [j for j in client.get(f"{api}/jobs", params={"dataset_id": ds_id}).json()
                       if j["kind"] == "review_issues" and j["status"] in ("queued", "running")], timeout_s)
    settings = get_settings()
    db = connect(settings)
    try:
        if version is None:
            return [], None
        dataset = db.execute("SELECT * FROM datasets WHERE id = ?", (ds_id,)).fetchone()
        first = review.stored(db, ds_id, version) or {}
        if not any(r["sev_source"] == "model" for r in first.values()):
            return [], None
        card = profile_service.get_or_build(settings, db, client.app.state.duckdb, dataset, version)
        out = []
        for column, damage in sorted({(d.column, d.kind) for d in case.damage}):
            rating = first.get(f"{damage.split(':')[0]}|{column}")
            if rating and rating["sev_source"] == "model":
                default = registry.get(damage.split(":")[0]).default_level
                out.append((column, damage, rating["sev"], expected(levels.role(column, card), rating["sev"], default)))
        review.review(settings, db, dataset, card, CallScope(user_id=dataset["user_id"], dataset_id=ds_id))
        second = review.stored(db, ds_id, version) or {}
        stable = all(second.get(k, {}).get("sev") == r["sev"] for k, r in first.items() if r["sev_source"] == "model")
        return out, stable
    finally:
        db.close()


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
        checks = ["", "| Set | Ratings | Report honest | Stable |", "|---|---|---|---|"]
        with TestClient(create_app()) as client:
            for case in cases():
                if names and case.name not in names:
                    continue
                result = run_case(client, case)
                lines.append(result.row())
                details += [f"| {case.name} | {k} | {r}/{n} | {w} |" for k, (r, n, w) in sorted(result.by_kind.items())]
                skips += [f"| {case.name} | {d} in {c or 'rows'} | {why.replace('|', '/')} |" for c, d, why in result.skipped]
                rated = [r for r in result.ratings if r[3] is not None]
                checks.append(f"| {case.name} | {sum(1 for r in rated if r[3])} of {len(rated)} as expected"
                              f"{'' if all(r[3] for r in rated) else ' (' + ', '.join(f'{c}: {d} {lv}' for c, d, lv, ok in rated if not ok) + ')'}"
                              f" | {_yes(result.honest)} | {_yes(result.stable)} |" if result.ratings else
                              f"| {case.name} | — | {_yes(result.honest)} | {_yes(result.stable)} |")
                steps += [f"| {case.name} | {name.replace('|', '/')} | {g} | {'—' if conf is None else f'{conf:.2f}'} |"
                          for name, g, conf in result.committed]
        get_settings.cache_clear()
    return "\n".join(lines + details + steps + skips + checks)


def _yes(value: bool | None) -> str:
    return "—" if value is None else "yes" if value else "no"
