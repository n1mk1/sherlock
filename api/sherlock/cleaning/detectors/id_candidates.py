"""ID candidates: columns that identify rows (almost all values distinct and present)."""

from sherlock.cleaning.detectors.base import Finding, Frame, examples

UNIQUE = 0.98
PRESENT = 0.95


def detect(frame: Frame) -> list[Finding]:
    findings = []
    rows = frame.rows
    for name, col in frame.columns.items():
        if not rows or col.text.empty:
            continue
        unique_ratio = col.text.nunique() / len(col.text)
        if col.role == "id" or (unique_ratio >= UNIQUE and len(col.text) >= PRESENT * rows and rows >= 20):
            findings.append(Finding(
                "id_candidates", name, len(col.text),
                "Use this column to identify rows; keep it out of charts and models.",
                examples(col.text.tolist()), {"unique_ratio": round(float(unique_ratio), 4)},
            ))
    return findings
