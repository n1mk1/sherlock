"""Shared types for detectors (PRD §7.3.2): code, not LLM, and generic: no dataset-specific rules."""

from dataclasses import dataclass, field

import pandas as pd

from sherlock.profile.infer import Column

MAX_EXAMPLES = 5


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


def examples(values) -> list:
    out = []
    for value in values:
        if value not in out:
            out.append(value)
        if len(out) == MAX_EXAMPLES:
            break
    return out
