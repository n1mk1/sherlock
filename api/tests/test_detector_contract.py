"""The detector contract (TRD §14, PRD CLEAN-12): every registered detector clears `cleaning/contract.py`,
so a new check, built in or from a pack, is held to the same bar as the 16 built-ins."""

import random

import pytest

from sherlock.cleaning import contract, registry
from sherlock.cleaning.detectors import fixtures

SPECS = registry.all()


@pytest.fixture(scope="module")
def big():
    return contract.big_frame()


@pytest.mark.parametrize("name", list(contract.CHECKS))
@pytest.mark.parametrize("spec", SPECS, ids=[s.id for s in SPECS])
def test_every_detector_clears_the_contract(spec, name, big):
    assert contract.CHECKS[name](spec, big) is None


def test_every_damage_kind_changes_its_fixture():
    for spec in SPECS:
        for kind in spec.injectors:
            if kind == "dmy_date":  # damage of a date column, which the fixture's date pair takes
                df = fixtures.clean_frame()
                changed = len(spec.injectors[kind].damage(df, "start_date", list(range(20)), random.Random(1)))
            else:
                changed = contract.damaged(spec, kind)[2]
            assert changed, f"{spec.id}:{kind} changed nothing"


def test_a_detector_that_breaks_the_contract_is_named():
    from dataclasses import replace

    noisy = replace(registry.get("outliers"), id="noisy", detect=lambda f: registry.get("missing").detect(f) or
                    [registry.get("missing").detect(contract.damaged(registry.get("missing"))[0])[0]])
    problems = dict(contract.check(noisy, contract.big_frame(rows=200)))
    assert "clean_shared" in problems and "well_behaved" in problems
