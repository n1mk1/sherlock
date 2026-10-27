"""Shared types for detectors (PRD §7.3.2): code, not LLM, and generic: no dataset-specific rules.

Each detector module exports a `DetectorSpec` (`SPEC`): every fact the rest of the app needs about it,
read through `cleaning/registry.py` (PRD CLEAN-12, TRD §7.1 step 4).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from sherlock.profile.infer import Column

MAX_EXAMPLES = 5
# The plan's sections for fixes that can change data (`plan.MODULES`, TRD §4.4).
GROUPS = ("types", "missing", "text", "records", "outliers", "other")
# What a finding does to an analysis, most severe first. Set on every spec, not used yet.
LEVELS = ("breaks", "skews", "splits", "check", "cosmetic")
SCOPES = ("column", "rows", "columns")


@dataclass
class Frame:
    """A version as the detectors see it: user columns only, with inferred types and roles."""

    df: pd.DataFrame
    columns: dict[str, Column]
    target_candidates: list[str] = field(default_factory=list)

    @property
    def rows(self) -> int:
        return len(self.df)


@dataclass
class Finding:
    detector: str
    column: str | None
    count: int
    proposal: str
    examples: list = field(default_factory=list)
    details: dict = field(default_factory=dict)


Edits = dict[tuple[int, str], Any]  # (row position, column) → the damaged value


@dataclass(frozen=True)
class Injector:
    """Seeded damage of the kind a detector finds, for the contract suite and the corruption eval
    (TRD §14). `damage(df, column, rows, rng)` returns the cells to change for the chosen row positions
    of `column`, in their order; a row it leaves out stays clean. `missing_ok`: a missing value is an
    honest recovery (a placeholder made missing). `share`: how much of the column the contract suite
    damages (ambiguous dates need every value)."""

    damage: Callable[[pd.DataFrame, str, list[int], Any], Edits]
    missing_ok: bool = False
    share: float = 0.1


@dataclass(frozen=True)
class DetectorSpec:
    id: str                       # stored as issues.detector
    label: str                    # plain words for the plan, the log and the offer ("placeholder values")
    description: str              # one sentence for the catalog (GET /detectors)
    group: str                    # the plan's section (GROUPS)
    weight: float                 # severity weight, 0–1 (TRD §7.1 step 4)
    default_level: str | None     # LEVELS; None for a detector whose issues are never changed (not rated)
    scope: str                    # "column", "rows" (whole rows) or "columns" (a pair or more)
    detect: Callable[[Frame], list[Finding]]
    version: int = 1              # bumped when what it finds changes
    never_change: str | None = None    # its issues are marked, never changed: the reason (TRD §7.2)
    skip_text: str | None = None       # the log's detail for an issue on a column it marks
    # The DataCard list its findings fill (`leakage_candidates`), as {column, target, reason} from `details`.
    marks_column: str | None = None
    type_fix: bool = False             # still fixed on an ID column: it only makes values readable
    domain_rule: bool = False          # quarantined by its own fix, never guessed (PRD CLEAN-4c)
    vote: bool = False                 # diagnosed three times, the majority wins (TRD §7.2)
    # A fix the code writes without the model: the domain rule's quarantine, or a fallback parse.
    code_fix: Callable[[dict], Any] | None = None
    runs_before: tuple[str, ...] = ()  # on the same column, attempted just before these detectors
    plan_extras: Callable[[dict], dict] | None = None  # extra fields on its plan item
    # Quality gates (TRD §14): its damage kinds, the first the default; a clean frame and the column its
    # damage goes in, where it finds nothing; and, for a detector that is never changed, a frame it must
    # find something in.
    injectors: dict[str, Injector] = field(default_factory=dict)
    clean_fixture: Callable[[], tuple[pd.DataFrame, str]] | None = None
    found_fixture: Callable[[], pd.DataFrame] | None = None
    enabled_by_default: bool = True
    source: str = "builtin"


def examples(values) -> list:
    out = []
    for value in values:
        if value not in out:
            out.append(value)
        if len(out) == MAX_EXAMPLES:
            break
    return out
