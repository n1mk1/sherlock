"""The detector contract (TRD §14, PRD CLEAN-12): one bar every registered detector clears, built in or
from a pack, run by `tests/test_detector_contract.py` and by `sherlock detectors check` when a pack is
installed. Each check returns None, or what is wrong.
"""

import json
import random
import re
import time

import pandas as pd

from sherlock.cleaning.detectors import fixtures
from sherlock.cleaning.detectors.base import DetectorSpec, Frame
from sherlock.stories.wording import wording_problem

MAX_SECONDS = 2.0
BIG_ROWS = 200_000
TOTAL_ROWS = 500_000
TOTAL_SECONDS = 60.0  # every enabled check together on 500,000 rows: inside the Profile budget (TRD §13)


def frame(df: pd.DataFrame, spec: DetectorSpec | None = None) -> Frame:
    """The frame a detector sees; the rule detector runs with its fixture rules."""
    from sherlock.profile.datacard import build_frame

    f = build_frame(df.astype(object).where(df.notna(), None), {})
    f.rules = list(spec.fixture_rules) if spec else []
    return f


def damaged(spec: DetectorSpec, kind: str | None = None, seed: int = 3) -> tuple[Frame, str, int]:
    """The spec's clean fixture with its damage (its first kind unless named): the frame, the damaged
    column and how many rows were changed."""
    df, column = spec.clean_fixture()
    inj = spec.injectors[kind or next(iter(spec.injectors))]
    rng = random.Random(seed)
    filled = [i for i in range(len(df)) if df.at[i, column] is not None]
    rows = rng.sample(filled, max(1, int(len(filled) * inj.share)))
    edits = inj.damage(df, column, rows, rng)
    dirty = df.copy()
    for (i, c), value in edits.items():
        dirty.at[i, c] = value
    return frame(dirty, spec), column, len({i for i, _ in edits})


def rated(spec: DetectorSpec) -> bool:
    return spec.never_change is None


def metadata(spec: DetectorSpec, big=None) -> str | None:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", spec.id) or not 0 <= spec.weight <= 1:
        return "the id must be snake_case and the weight within 0–1"
    for text in (spec.label, spec.description):
        if not text.strip() or wording_problem(text):
            return f"label and description need plain wording: {text!r} ({wording_problem(text)})"
    return None


def clean_shared(spec: DetectorSpec, big=None) -> str | None:
    if rated(spec) and spec.detect(frame(fixtures.clean_frame(), spec)):
        return "it finds something in the shared clean frame"
    return None


def clean_own(spec: DetectorSpec, big=None) -> str | None:
    if not rated(spec):
        return None
    if not (spec.clean_fixture and spec.injectors):
        return "a rated detector needs a clean fixture and an injector"
    df, column = spec.clean_fixture()
    if column not in df.columns:
        return f"its fixture has no column {column!r}"
    if spec.detect(frame(df, spec)):
        return "it finds something in its own clean fixture, so a fix can't be shown to resolve it"
    return None


def finds_damage(spec: DetectorSpec, big=None) -> str | None:
    if not rated(spec):
        if not spec.found_fixture:
            return "a detector that never changes data needs a fixture it must find"
        return None if spec.detect(frame(spec.found_fixture(), spec)) else "it finds nothing in its found fixture"
    if not (spec.clean_fixture and spec.injectors):
        return None  # clean_own reports it
    f, column, n = damaged(spec)
    if n == 0:
        return "its injector changed nothing"
    got = sum(x.count for x in spec.detect(f) if spec.scope == "rows" or x.column == column)
    return None if got >= n else f"it found {got} of {n} damaged rows"


def well_behaved(spec: DetectorSpec, big=None) -> str | None:
    """Deterministic, pure (the frame is unchanged) and well-shaped findings."""
    if rated(spec) and not (spec.clean_fixture and spec.injectors):
        return None
    f = damaged(spec)[0] if rated(spec) else frame(spec.found_fixture(), spec)
    before = f.df.copy()
    first, second = spec.detect(f), spec.detect(f)
    if [vars(x) for x in first] != [vars(x) for x in second]:
        return "two runs on the same frame gave different findings"
    if not f.df.equals(before):
        return "it changed the frame"
    for x in first:
        if x.detector.split(":")[0] != spec.id or x.count <= 0:
            return f"a finding must carry its detector's id and a count above 0: {x.detector}, {x.count}"
        if (x.column is None) != (spec.scope == "rows") or (x.column is not None and x.column not in f.columns):
            return f"a finding's column must be in the frame (None only for a rows scope): {x.column!r}"
        if len(x.examples) > 5:
            return "at most five examples"
        try:
            json.dumps(x.details)
        except TypeError:
            return "details must be JSON-serialisable"
        if wording_problem(x.proposal):
            return f"the proposal needs plain wording: {x.proposal!r}"
    return None


def applies(spec: DetectorSpec, big=None) -> str | None:
    """It reports only columns of the types it says it reads (`applies_to`)."""
    if not spec.applies_to or (rated(spec) and not (spec.clean_fixture and spec.injectors)):
        return None
    f = damaged(spec)[0] if rated(spec) else frame(spec.found_fixture(), spec)
    for x in spec.detect(f):
        if x.column is not None and f.columns[x.column].type not in spec.applies_to:
            return f"it reported {x.column}, a {f.columns[x.column].type} column, outside its types {sorted(spec.applies_to)}"
    return None


def big_frame(rows: int = BIG_ROWS) -> Frame:
    """A frame of every column type, for the time budget."""
    df = fixtures.clean_frame(rows=rows, seed=11)
    for column, values in (("place", ["Zürich", "Genève", "Köln"]), ("weight", ["5 kg", "12 kg", "7 kg"]),
                           ("site", ["Northgate", "Riverside", "Lakeview", "Oakwood"])):
        df.insert(len(df.columns) - 1, column, [values[i % len(values)] for i in range(rows)])
    return frame(df)


def fast(spec: DetectorSpec, big: Frame | None = None) -> str | None:
    big = big or big_frame()
    started = time.perf_counter()
    spec.detect(big)
    took = time.perf_counter() - started
    return None if took <= MAX_SECONDS else f"it took {took:.1f} s on {len(big.df):,} rows (budget {MAX_SECONDS:g} s)"


def total_seconds(specs, big: Frame) -> float:
    """Every given check, one after another, on one frame: what a profile spends on detectors."""
    started = time.perf_counter()
    for spec in specs:
        spec.detect(big)
    return time.perf_counter() - started


def overlaps(specs) -> list[tuple[str, str, str]]:
    """Pairs of checks that flag the same damaged column: each rated check's damage, on its fixture, run
    through every other check (spec id, other id, column). For review, not a failure: two checks can see
    one problem from two sides."""
    out = []
    for spec in specs:
        if not (rated(spec) and spec.clean_fixture and spec.injectors):
            continue
        f, column, _ = damaged(spec)
        for other in specs:
            if other.id != spec.id and rated(other) and any(x.column == column for x in other.detect(f)):
                out.append((spec.id, other.id, column))
    return out


CHECKS = {"metadata": metadata, "clean_shared": clean_shared, "clean_own": clean_own, "finds_damage": finds_damage,
          "well_behaved": well_behaved, "applies": applies, "fast": fast}


def check(spec: DetectorSpec, big: Frame | None = None) -> list[tuple[str, str]]:
    """Every check's problem for a spec, empty when it clears the bar."""
    return [(name, problem) for name, fn in CHECKS.items() if (problem := fn(spec, big))]
