"""Installable detector packs and DETECTORS_OFF (TRD §7.1 step 4): a pack loads only when the operator
allows it, a refused pack is skipped and listed, and a detector can be turned off without a deploy."""

import sys
from importlib.metadata import EntryPoint
from pathlib import Path

import pytest

from sherlock.cleaning import contract, registry

PACK = Path(__file__).resolve().parents[1] / "samples" / "detector_pack"


class _Settings:
    def __init__(self, plugins="off", off=""):
        self.detector_plugins, self.detectors_off = plugins, off


@pytest.fixture
def entry_points(monkeypatch):
    """The example pack, and one whose spec repeats a built-in's id, as installed entry points."""
    monkeypatch.syspath_prepend(str(PACK))
    monkeypatch.setattr(registry, "_specs", dict(registry._specs))
    monkeypatch.setattr(registry, "_packs", {})
    monkeypatch.setattr(registry, "_refused", {})
    monkeypatch.setattr(registry, "_off", set())
    monkeypatch.setitem(sys.modules, "_bad_pack", type(sys)("_bad_pack"))
    sys.modules["_bad_pack"].SPECS = (registry.get("missing"),)  # "missing" is already registered
    eps = [EntryPoint("example", "sherlock_example.detectors:SPECS", registry.GROUP),
           EntryPoint("clash", "_bad_pack:SPECS", registry.GROUP)]
    monkeypatch.setattr(registry.metadata, "entry_points", lambda group: eps if group == registry.GROUP else [])
    yield  # monkeypatch puts the registry back


@pytest.mark.usefixtures("entry_points")
def test_packs_are_off_unless_the_operator_allows_them():
    registry.configure(_Settings())
    assert "single_value" not in {s.id for s in registry.all()} and registry.packs()["packs"] == []


@pytest.mark.usefixtures("entry_points")
def test_an_allowed_pack_loads_and_a_refused_one_is_listed():
    registry.configure(_Settings("all"))
    spec = registry.get("single_value")
    assert spec.source == "pack" and spec in registry.enabled()
    got = registry.packs()
    assert [p["name"] for p in got["packs"]] == ["example"] and got["packs"][0]["detectors"] == ["single_value"]
    assert [p["name"] for p in got["refused"]] == ["clash"] and "already registered" in got["refused"][0]["reason"]
    assert contract.check(spec, contract.big_frame(rows=2000)) == []  # the example clears the contract
    registry.configure(_Settings("all"))  # a second start in one process loads nothing twice
    assert [s.id for s in registry.all()].count("single_value") == 1


@pytest.mark.usefixtures("entry_points")
def test_an_allowlist_loads_only_the_packs_it_names():
    registry.configure(_Settings("example"))
    assert registry.get("single_value").source == "pack" and registry.packs()["refused"] == []


@pytest.mark.usefixtures("entry_points")
def test_detectors_off_turns_a_detector_off():
    registry.configure(_Settings(off="outliers, mojibake"))
    ids = {s.id for s in registry.enabled()}
    assert "outliers" not in ids and "mojibake" not in ids and "missing" in ids
    assert registry.get("outliers") in registry.all()  # still known, so old issues display
    assert registry.packs()["off"] == ["mojibake", "outliers"]


def test_healthz_lists_the_detector_packs(client):
    body = client.get("/healthz").json()
    assert body["detectors"] == {"packs": [], "refused": [], "off": []}
