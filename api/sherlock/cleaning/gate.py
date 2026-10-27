"""The gate (TRD §7.2, PRD CLEAN-4): commit, commit with a flag, or skip.

confidence = 0.6 × best score + 0.2 × agreement + 0.2 × (1 if the review passed else 0),
where agreement is the output agreement (`verifiers.compare`): the share of candidates
whose results match the best one's on at least 99% of the cells either changes. The review passes
unless the critic says the step changed something it shouldn't (or the review couldn't be read).
Disagreement (`disagree`): when two candidates that pass the hard checks give different values to
more than 1% of the cells they both change, the step is skipped, a requested one too: the data
doesn't settle which is right. The loop applies it on the sample, before the full-data run.
The critic's verdict that the step changed something it shouldn't skips the step in the loop (owner's
decision, 2026-10-25). The critic's list of concerns is recorded on the step but doesn't lower confidence: concerns on
their own can't keep a step from committing (owner's decision, 2026-10-24).
blast = cells changed / cells in the dataset, where a newly quarantined row counts as all of its
cells (`cells_affected`): it leaves every answer and model, so it isn't one cell's change.
A step the user asked for in the cleaning plan (`requested`, PRD CLEAN-8b) that would be skipped for
low confidence commits with a flag instead, so it can be undone; with no candidate passing the hard
checks it is still skipped.
A domain-rule issue (`impossible_values`: a negative age, an age of 999; `domain_rule`) is kept the
same way, flagged rather than skipped at low confidence. When the critic objects to its fix and the
fix only quarantines the rows the rule names, the loop flags it (`overrule`) instead of skipping it:
the rule, not the model, says those values are impossible.
A near-duplicate merge that joins two spellings that are both common (a letter left out, "Wst" /
"West", `details.review_pairs`) is never a plain commit: it is flagged for review (`review`).
"""

from dataclasses import dataclass

DISAGREE_SHARE = 0.01
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


def disagree(share: float) -> str | None:
    """The skip reason when candidates disagree on more than 1% of the cells they both change."""
    return f"the candidates disagree on {share:.0%} of the cells they both change" if share > DISAGREE_SHARE else None


def cells_affected(cells_changed: int, rows_quarantined: int, columns: int, total_cells: int) -> int:
    """The blast's numerator: changed cells plus every cell of a newly quarantined row (cells
    changed inside those rows may count twice, so it's capped at the dataset's cells)."""
    return min(cells_changed + rows_quarantined * max(columns, 1), total_cells)


def decide(scores: list[float], agree: float, review_ok: bool, cells_changed: int, total_cells: int,
           requested: bool = False, domain_rule: bool = False) -> Decision:
    best = max(scores) if scores else 0.0
    confidence = round(0.6 * best + 0.2 * agree + 0.2 * (1.0 if review_ok else 0.0), 4)
    blast = cells_changed / total_cells if total_cells else 0.0
    if best == 0.0:
        return Decision("skip", confidence, agree, blast, "no candidate passed the checks")
    if confidence >= COMMIT_CONFIDENCE and blast < COMMIT_MAX_BLAST:
        return Decision("commit", confidence, agree, blast)
    if confidence >= FLAG_CONFIDENCE:
        reason = "changes more than a fifth of the data" if blast >= COMMIT_MAX_BLAST else f"medium confidence ({confidence:.2f})"
        return Decision("flag", confidence, agree, blast, reason)
    if requested:
        return Decision("flag", confidence, agree, blast, f"low confidence ({confidence:.2f}); kept because you asked for it")
    if domain_rule:
        return Decision("flag", confidence, agree, blast,
                        f"low confidence ({confidence:.2f}); kept because the values break the column's domain rule")
    return Decision("skip", confidence, agree, blast, f"low confidence ({confidence:.2f})")


def overrule(decision: Decision, rule: str | None) -> Decision:
    """A domain rule's quarantine the critic objected to: committed with a flag, never skipped."""
    why = (f"the review objected, but every row it sets aside breaks the rule ({rule})" if rule
           else "the review objected, but every row it sets aside breaks the column's domain rule")
    return Decision("flag", decision.confidence, decision.agreement, decision.blast, why)


def review(decision: Decision, pairs: list) -> Decision:
    """A merge of two common spellings: flagged for review rather than committed."""
    shown = "; ".join(f"{a} → {b}" for a, b in pairs[:3])
    return Decision("flag", decision.confidence, decision.agreement, decision.blast,
                    f"merges spellings that are both common ({shown}); check them")
