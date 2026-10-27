"""Missing values and missingness patterns: per column, plus columns that go missing together."""

from sherlock.cleaning.detectors.base import DetectorSpec, Finding, Frame

TOGETHER = 0.9  # Jaccard overlap of two columns' missing masks


def detect(frame: Frame) -> list[Finding]:
    masks = {name: c.raw.isna() for name, c in frame.columns.items() if c.missing}
    findings = []
    for name, mask in masks.items():
        col = frame.columns[name]
        if col.type == "empty":
            findings.append(Finding("missing", name, col.missing, "This column has no values. Keep it out of charts and models.",
                                    details={"all_missing": True}))
            continue
        together = []
        for other, other_mask in masks.items():
            if other == name or frame.columns[other].type == "empty":
                continue
            union = int((mask | other_mask).sum())
            if union and int((mask & other_mask).sum()) / union >= TOGETHER:
                together.append(other)
        findings.append(Finding(
            "missing", name, col.missing,
            "Fill from a rule over related columns where one fits; otherwise leave the values missing. "
            "Never fill with a placeholder such as Unknown. Rows are never dropped.",
            details={"missing_with": together} if together else {},
        ))
    return findings


SPEC = DetectorSpec(
    "missing", "missing values", "Missing values per column, and columns that go missing together.",
    group="missing", weight=0.5, default_level="check", scope="column", detect=detect,
)
