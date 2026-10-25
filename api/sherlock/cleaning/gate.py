"""The gate (TRD §7.2, PRD CLEAN-4): commit, commit with a flag, or skip.

confidence = 0.6 × best score + 0.2 × agreement + 0.2 × (1 if the review passed else 0),
where agreement is the share of candidates scoring within 0.1 of the best, and the review passes
unless the critic says the step changed something it shouldn't (or the review couldn't be read).
The critic's verdict that the step changed something it shouldn't skips the step in the loop (owner's
decision, 2026-10-25). The critic's list of concerns is recorded on the step but doesn't lower confidence: concerns on
their own can't keep a step from committing (owner's decision, 2026-10-24).
blast = cells changed / cells in the dataset, where a newly quarantined row counts as all of its
cells (`cells_affected`): it leaves every widget, model and story, so it isn't one cell's change.
"""

from dataclasses import dataclass

COMMIT_CONFIDENCE = 0.8
COMMIT_MAX_BLAST = 0.2
FLAG_CONFIDENCE = 0.55


@dataclass(frozen=True)
class Decision:
    gate: str  # commit | flag | skip
    confidence: float
    agreement: float
    blast: float
    reason: str | None = None


def agreement(scores: list[float]) -> float:
    if not scores:
        return 0.0
    best = max(scores)
    return sum(1 for s in scores if best - s <= 0.1) / len(scores)


def cells_affected(cells_changed: int, rows_quarantined: int, columns: int, total_cells: int) -> int:
    """The blast's numerator: changed cells plus every cell of a newly quarantined row (cells
    changed inside those rows may count twice, so it's capped at the dataset's cells)."""
    return min(cells_changed + rows_quarantined * max(columns, 1), total_cells)


def decide(scores: list[float], review_ok: bool, cells_changed: int, total_cells: int) -> Decision:
    best = max(scores) if scores else 0.0
    agree = agreement(scores)
    confidence = round(0.6 * best + 0.2 * agree + 0.2 * (1.0 if review_ok else 0.0), 4)
    blast = cells_changed / total_cells if total_cells else 0.0
    if best == 0.0:
        return Decision("skip", confidence, agree, blast, "no candidate passed the checks")
    if confidence >= COMMIT_CONFIDENCE and blast < COMMIT_MAX_BLAST:
        return Decision("commit", confidence, agree, blast)
    if confidence >= FLAG_CONFIDENCE:
        reason = "changes more than a fifth of the data" if blast >= COMMIT_MAX_BLAST else f"medium confidence ({confidence:.2f})"
        return Decision("flag", confidence, agree, blast, reason)
    return Decision("skip", confidence, agree, blast, f"low confidence ({confidence:.2f})")
