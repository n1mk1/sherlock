"""The detector contract (TRD §14, PRD CLEAN-12): one suite every registered detector passes, so a new
check, built in or added, is held to the same bar as the 16 built-ins."""

import json
import random
import re
import time

import pandas as pd
import pytest

from sherlock.cleaning import registry
from sherlock.cleaning.detectors import fixtures
from sherlock.profile.datacard import build_frame
from sherlock.stories.wording import wording_problem

SPECS = registry.all()
RATED = [s for s in SPECS if s.never_change is None]
MAX_SECONDS = 2.0
BIG_ROWS = 200_000


def ids(specs):
    return [s.id for s in specs]


def frame(df: pd.DataFrame):
    return build_frame(df.astype(object).where(df.notna(), None), {})


def damaged(spec, kind: str | None = None, seed: int = 3):
    """The spec's clean fixture with its injector's damage: (frame, column, cells damaged)."""
    df, column = spec.clean_fixture()
    kind = kind or next(iter(spec.injectors))
    inj = spec.injectors[kind]
    rng = random.Random(seed)
    filled = [i for i in range(len(df)) if df.at[i, column] is not None]
    rows = rng.sample(filled, max(1, int(len(filled) * inj.share)))
    edits = inj.damage(df, column, rows, rng)
    dirty = df.copy()
    for (i, c), value in edits.items():
        dirty.at[i, c] = value
    return frame(dirty), column, len({i for i, _ in edits})


def found_on(spec, findings, column):
    return sum(f.count for f in findings if spec.scope == "rows" or f.column == column)


@pytest.mark.parametrize("spec", SPECS, ids=ids(SPECS))
def test_metadata(spec):
    assert re.fullmatch(r"[a-z][a-z0-9_]*", spec.id) and 0 <= spec.weight <= 1
    for text in (spec.label, spec.description):
        assert text.strip() and wording_problem(text) is None, text


@pytest.mark.parametrize("spec", RATED, ids=ids(RATED))
def test_finds_nothing_in_the_shared_clean_frame(spec):
    assert spec.detect(frame(fixtures.clean_frame())) == []


@pytest.mark.parametrize("spec", RATED, ids=ids(RATED))
def test_finds_nothing_in_its_own_clean_fixture(spec):
    # So once the damage is undone, the issue is gone: the verifier's "share of the issue left" works.
    assert spec.clean_fixture and spec.injectors, f"{spec.id} needs a clean fixture and an injector"
    df, column = spec.clean_fixture()
    assert column in df.columns
    assert spec.detect(frame(df)) == []


@pytest.mark.parametrize("spec", RATED, ids=ids(RATED))
def test_finds_its_damage(spec):
    f, column, n = damaged(spec)
    assert n > 0, f"{spec.id}'s injector changed nothing"
    assert found_on(spec, spec.detect(f), column) >= n


@pytest.mark.parametrize("spec", [s for s in SPECS if s.never_change], ids=ids([s for s in SPECS if s.never_change]))
def test_a_detector_that_never_changes_data_finds_its_fixture(spec):
    assert spec.found_fixture, f"{spec.id} needs a fixture it must find"
    assert spec.detect(frame(spec.found_fixture()))


def _subject(spec):
    return damaged(spec)[0] if spec.injectors else frame(spec.found_fixture())


@pytest.mark.parametrize("spec", SPECS, ids=ids(SPECS))
def test_deterministic_pure_and_well_shaped(spec):
    f = _subject(spec)
    before = f.df.copy()
    first, second = spec.detect(f), spec.detect(f)
    assert [vars(x) for x in first] == [vars(x) for x in second]
    pd.testing.assert_frame_equal(f.df, before)
    for x in first:
        assert x.detector == spec.id and x.count > 0
        assert (x.column is None) == (spec.scope == "rows") and (x.column is None or x.column in f.columns)
        assert len(x.examples) <= 5
        json.dumps(x.details)
        assert wording_problem(x.proposal) is None, x.proposal


@pytest.fixture(scope="module")
def big_frame():
    df = fixtures.clean_frame(rows=BIG_ROWS, seed=11)
    for column, values in (("place", ["Zürich", "Genève", "Köln"]), ("weight", ["5 kg", "12 kg", "7 kg"]),
                           ("site", ["Northgate", "Riverside", "Lakeview", "Oakwood"])):
        df.insert(len(df.columns) - 1, column, [values[i % len(values)] for i in range(BIG_ROWS)])
    return frame(df)


@pytest.mark.parametrize("spec", SPECS, ids=ids(SPECS))
def test_runs_within_its_time_budget(spec, big_frame):
    started = time.perf_counter()
    spec.detect(big_frame)
    assert time.perf_counter() - started <= MAX_SECONDS, f"{spec.id} took too long on {BIG_ROWS:,} rows"


def test_every_damage_kind_changes_its_fixture():
    for spec in RATED:
        for kind in spec.injectors:
            if kind == "dmy_date":  # damage of a date column, which the fixture's date pair takes
                df = fixtures.clean_frame()
                edits = spec.injectors[kind].damage(df, "start_date", list(range(20)), random.Random(1))
            else:
                _, _, n = damaged(spec, kind)
                edits = {n: n} if n else {}
            assert edits, f"{spec.id}:{kind} changed nothing"
