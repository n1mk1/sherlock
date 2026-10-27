"""The detector registry (PRD CLEAN-12, TRD §7.1 step 4): one `DetectorSpec` per check, and the one
place the rest of the app learns what a detector is called, where it goes in the plan, how much it
weighs and how the Cleaner treats it.

The built-ins register at import, in their run order; a spec `register` refuses is a bug, so the API
doesn't start. `get` of an id no longer registered (an issue row from a check since removed) returns an
"unknown detector" spec that finds nothing, so old plans and reports still display.

Severity = min(count / rows, 1) × the spec's weight.
"""

import re

from sherlock.cleaning.detectors import BUILTINS
from sherlock.cleaning.detectors.base import GROUPS, LEVELS, SCOPES, DetectorSpec, Finding, Frame

ID = re.compile(r"^[a-z][a-z0-9_]*$")

_specs: dict[str, DetectorSpec] = {}


class RegistryError(ValueError):
    """A spec the registry refuses: a duplicate id, an unknown group, level or scope, a weight outside
    0–1, or a `runs_before` that names an unknown id or makes a cycle."""


def register(*specs: DetectorSpec) -> None:
    """Register specs together, all or nothing: a `runs_before` may name one registered in the same call."""
    batch: dict[str, DetectorSpec] = {}
    for s in specs:
        if not ID.match(s.id):
            raise RegistryError(f"Detector id {s.id!r} isn't snake_case.")
        if s.id in _specs or s.id in batch:
            raise RegistryError(f"Detector {s.id!r} is already registered.")
        if s.group not in GROUPS:
            raise RegistryError(f"{s.id}: unknown group {s.group!r}; use one of {', '.join(GROUPS)}.")
        if s.default_level is None and s.never_change is None:
            raise RegistryError(f"{s.id}: a detector whose issues can change needs a default level.")
        if s.default_level is not None and s.default_level not in LEVELS:
            raise RegistryError(f"{s.id}: unknown level {s.default_level!r}; use one of {', '.join(LEVELS)}.")
        if s.scope not in SCOPES:
            raise RegistryError(f"{s.id}: unknown scope {s.scope!r}; use one of {', '.join(SCOPES)}.")
        if not 0 <= s.weight <= 1:
            raise RegistryError(f"{s.id}: weight {s.weight} is outside 0–1.")
        if not s.label.strip() or not s.description.strip():
            raise RegistryError(f"{s.id}: a label and a description are required.")
        batch[s.id] = s
    known = {**_specs, **batch}
    for s in batch.values():
        for after in s.runs_before:
            if after not in known:
                raise RegistryError(f"{s.id}: runs_before names unknown detector {after!r}.")
    _check_cycles(known)
    _specs.update(batch)


def _check_cycles(specs: dict[str, DetectorSpec]) -> None:
    state: dict[str, str] = {}  # "open" while on the path, "done" once every later one is checked

    def visit(i: str, path: list[str]) -> None:
        if state.get(i) == "done":
            return
        if state.get(i) == "open":
            raise RegistryError(f"runs_before makes a cycle: {' → '.join(path[path.index(i):] + [i])}.")
        state[i] = "open"
        for after in specs[i].runs_before:
            visit(after, path + [i])
        state[i] = "done"

    for i in specs:
        visit(i, [])


def all() -> list[DetectorSpec]:  # noqa: A001 - the registry's own name for every spec
    """Every registered spec, in run order."""
    return list(_specs.values())


def enabled() -> list[DetectorSpec]:
    """The specs that run on every version, in run order."""
    return [s for s in _specs.values() if s.enabled_by_default]


def get(detector: str) -> DetectorSpec:
    """The spec for an id, or an "unknown detector" spec that finds nothing and changes nothing special."""
    spec = _specs.get(detector)
    if spec is not None:
        return spec
    return DetectorSpec(detector, detector.replace("_", " "), "A check that is no longer installed.",
                        group="other", weight=0.0, default_level="check", scope="column",
                        detect=lambda frame: [], enabled_by_default=False, source="unknown")


def injector(name: str):
    """A damage kind by name, "<detector>" (its first kind) or "<detector>:<kind>", for the corruption
    eval and the contract suite (TRD §14). KeyError for one no spec has."""
    detector, _, kind = name.partition(":")
    injectors = get(detector).injectors
    if not injectors or (kind and kind not in injectors):
        raise KeyError(f"no damage kind {name!r}")
    return injectors[kind or next(iter(injectors))]


def label(detector: str) -> str:
    return get(detector).label


def severity(finding: Finding, rows: int) -> float:
    share = min(finding.count / rows, 1.0) if rows else 0.0
    return round(share * get(finding.detector).weight, 4)


def run_all(frame: Frame) -> list[tuple[Finding, float]]:
    """Every enabled detector's findings with severities, most severe first."""
    results = []
    for spec in enabled():
        for finding in spec.detect(frame):
            if finding.count > 0:
                results.append((finding, severity(finding, frame.rows)))
    results.sort(key=lambda pair: pair[1], reverse=True)
    return results


def catalog() -> list[dict]:
    """`GET /detectors` (TRD §4.4): what each registered check is, in run order."""
    return [{"id": s.id, "label": s.label, "description": s.description, "group": s.group,
             "default_level": s.default_level, "source": s.source} for s in _specs.values()]


register(*BUILTINS)
