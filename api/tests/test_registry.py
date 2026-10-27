"""The detector registry (PRD CLEAN-12): what it refuses, what it returns for an id it no longer has,
and the catalog behind `GET /detectors`."""

from dataclasses import replace

import pytest

from sherlock.cleaning import registry
from sherlock.cleaning.detectors import BUILTINS
from sherlock.cleaning.detectors.base import DetectorSpec
from sherlock.cleaning.registry import RegistryError


@pytest.fixture(autouse=True)
def own_registry(monkeypatch):
    """Each test registers into a copy, so the built-ins stay as they are for the other tests."""
    monkeypatch.setattr(registry, "_specs", dict(registry._specs))


def spec(id="extra_check", **changes) -> DetectorSpec:
    base = DetectorSpec(id, "extra findings", "Finds nothing; a test spec.", group="other", weight=0.5,
                        default_level="check", scope="column", detect=lambda frame: [])
    return replace(base, **changes)


def test_the_sixteen_built_ins_and_the_rule_detector_register_in_run_order():
    assert [s.id for s in registry.all()] == [s.id for s in BUILTINS] + ["rule"]
    assert len(BUILTINS) == 16 and registry.enabled() == registry.all()
    assert registry.get("rule:rul_123").id == "rule"  # a rule's finding is the rule detector's
    assert registry.get("sentinels").runs_before == ("impossible_values",)


def test_a_new_spec_registers_and_is_found():
    registry.register(spec())
    assert registry.get("extra_check").label == "extra findings" and registry.label("extra_check") == "extra findings"


@pytest.mark.parametrize("bad,message", [
    (spec(id="sentinels"), "already registered"),
    (spec(id="Not Snake"), "snake_case"),
    (spec(group="kept"), "unknown group"),
    (spec(default_level="urgent"), "unknown level"),
    (spec(default_level=None), "needs a default level"),
    (spec(scope="table"), "unknown scope"),
    (spec(weight=1.2), "outside 0–1"),
    (spec(weight=-0.1), "outside 0–1"),
    (spec(depth=0), "depth 0 is outside 1–5"),
    (spec(depth=6), "depth 6 is outside 1–5"),
    (spec(label=" "), "label and a description"),
    (spec(runs_before=("no_such_check",)), "unknown detector"),
])
def test_register_refuses_a_bad_spec(bad, message):
    before = registry.all()
    with pytest.raises(RegistryError, match=message):
        registry.register(bad)
    assert registry.all() == before


def test_register_refuses_a_duplicate_within_one_call():
    with pytest.raises(RegistryError, match="already registered"):
        registry.register(spec(), spec())


def test_register_refuses_a_runs_before_cycle_and_registers_nothing():
    with pytest.raises(RegistryError, match="cycle"):
        registry.register(spec("first", runs_before=("second",)), spec("second", runs_before=("first",)))
    with pytest.raises(RegistryError, match="cycle"):
        registry.register(spec("loops", runs_before=("loops",)))
    assert not {"first", "second", "loops"} & {s.id for s in registry.all()}


def test_runs_before_may_name_a_spec_of_the_same_call():
    registry.register(spec("first", runs_before=("second",)), spec("second"))
    assert registry.get("first").runs_before == ("second",)


def test_a_removed_detector_still_displays():
    gone = registry.get("finance_check")
    assert gone.label == "finance check" and gone.group == "other" and gone.weight == 0.0
    assert gone.detect(None) == [] and gone.code_fix is None and gone.never_change is None
    assert gone not in registry.all()


def test_get_detectors_lists_the_sixteen_and_the_rule_detector(client):
    r = client.get("/api/v1/detectors")
    assert r.status_code == 200
    found = r.json()["detectors"]
    assert [d["id"] for d in found] == [s.id for s in BUILTINS] + ["rule"]
    by_id = {d["id"]: d for d in found}
    assert by_id["sentinels"] == {"id": "sentinels", "label": "placeholder values",
                                  "description": registry.get("sentinels").description, "group": "missing",
                                  "default_level": "skews", "depth": 1, "source": "builtin"}
    assert by_id["leakage"]["default_level"] is None  # never changed, so not rated


def test_a_refused_built_in_stops_the_api_from_starting(monkeypatch):
    import inspect

    # At import the registry registers the built-ins with no guard, so a refusal is an import error.
    assert inspect.getsource(registry).rstrip().endswith("register(*BUILTINS, RULE)")
    monkeypatch.setattr(registry, "_specs", {})  # the registry as the import starts
    with pytest.raises(RegistryError, match="outside 0–1"):
        registry.register(*BUILTINS, spec(id="broken_built_in", weight=7.0))
    assert registry.all() == []  # all or nothing: nothing half-registered


def test_each_layer_holds_the_checks_that_look_that_wide():
    # PRD CLEAN-15: single values, each column, rows against rows, columns against columns, the dataset.
    layers = {n: sorted(s.id for s in BUILTINS if s.depth == n) for n in range(1, 6)}
    assert layers == {
        1: ["missing", "mojibake", "numbers_as_text", "sentinels", "whitespace_case"],
        2: ["ambiguous_dates", "id_candidates", "impossible_values", "mixed_types", "outliers", "unit_mixes"],
        3: ["duplicates", "near_duplicate_categories"],
        4: ["cross_column", "functional_dependency"],
        5: ["leakage"],
    }
    assert registry.get("rule").depth == 1  # your checks run at every depth
    # A finding's own depth wins over its spec's, as its other settings do.
    assert registry.within({"detector": "leakage", "details": {}}, 4) is False
    assert registry.within({"detector": "leakage", "details": {"depth": 2}}, 4) is True
    assert registry.within({"detector": "sentinels", "details": {}}, 1) is True
