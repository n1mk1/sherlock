"""The gate (TRD §7.2, PRD CLEAN-4): commit, commit with a flag, or skip.

confidence = 0.6 × best score + 0.2 × agreement + 0.2 × (1 if the critic has no concerns else 0),
where agreement is the share of candidates scoring within 0.1 of the best.
blast = cells changed / cells in the dataset.
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


def decide(scores: list[float], critic_clean: bool, cells_changed: int, total_cells: int) -> Decision:
    best = max(scores) if scores else 0.0
    agree = agreement(scores)
    confidence = round(0.6 * best + 0.2 * agree + 0.2 * (1.0 if critic_clean else 0.0), 4)
    blast = cells_changed / total_cells if total_cells else 0.0
    if best == 0.0:
        return Decision("skip", confidence, agree, blast, "no candidate passed the checks")
    if confidence >= COMMIT_CONFIDENCE and blast < COMMIT_MAX_BLAST:
        return Decision("commit", confidence, agree, blast)
    if confidence >= FLAG_CONFIDENCE:
        reason = "changes more than a fifth of the data" if blast >= COMMIT_MAX_BLAST else f"medium confidence ({confidence:.2f})"
        return Decision("flag", confidence, agree, blast, reason)
    return Decision("skip", confidence, agree, blast, f"low confidence ({confidence:.2f})")
