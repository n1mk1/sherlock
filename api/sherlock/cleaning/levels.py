"""Severity levels (PRD CLEAN-8c, TRD §7.2): what a finding does to an analysis, as a category, never a
computed number (Rule 2).

| Level | Plan heading | Meaning |
|---|---|---|
| breaks | Breaks answers | answers or models would be wrong |
| skews | Skews answers | answers would be biased |
| splits | Splits groups | groups would be split or mislabeled |
| check | Worth a look | probably real; worth a look |
| cosmetic | Cosmetic | doesn't change any answer |

An issue's default level is its detector's `spec.default_level`, adjusted by code for its column: one
level more severe on the target or a measure, one less on free text (never below cosmetic). A finding
over several columns takes the most important role among them; a finding over whole rows, and a
detector whose default is `check` (an observation whatever its column), take no adjustment. A
detector whose issues are never changed (leakage, IDs) has no level.
"""

from sherlock.cleaning import registry
from sherlock.cleaning.detectors.base import LEVELS

HEADINGS = {"breaks": "Breaks answers", "skews": "Skews answers", "splits": "Splits groups",
            "check": "Worth a look", "cosmetic": "Cosmetic"}


def rank(level: str | None) -> int:
    """0 for breaks … 4 for cosmetic; a level-less issue (never changed) sorts first, -1."""
    return LEVELS.index(level) if level in LEVELS else -1


def columns_of(issue: dict, card: dict) -> list[str]:
    """The finding's columns: its own, and for a finding over several columns the others its details
    name (an earlier column, a determinant)."""
    names = {c["name"] for c in card.get("columns", [])}
    out = [issue["column"]] if issue.get("column") else []
    for value in (issue.get("details") or {}).values():
        if isinstance(value, str) and value in names and value not in out:
            out.append(value)
    return out


def role(column: str, card: dict) -> str:
    """"target" for a target candidate, else the column's DataCard role."""
    if column in card.get("target_candidates", []):
        return "target"
    entry = next((c for c in card.get("columns", []) if c["name"] == column), None)
    return entry.get("role", "") if entry else ""


# The ladder a role moves a level along; "check" (worth a look) is off it: an observation stays one.
LADDER = ("breaks", "skews", "splits", "cosmetic")


def shift(level: str, by: int) -> str:
    return LADDER[min(max(LADDER.index(level) + by, 0), len(LADDER) - 1)]


def default_level(issue: dict, card: dict) -> str | None:
    """The level code gives an issue before any review (PRD CLEAN-8c)."""
    spec = registry.get(issue["detector"])
    base = spec.default_level
    if base is None or base == "check" or spec.scope == "rows":
        return base
    roles = {role(c, card) for c in columns_of(issue, card)}
    if roles & {"target", "measure"}:
        return shift(base, -1)
    if roles and roles <= {"free_text"}:
        return shift(base, 1)
    return base
