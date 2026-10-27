"""Exact and near duplicate rows (near: equal after trimming and case-folding every value).
Examples are `_row_id`s."""

from sherlock.cleaning.detectors.base import DetectorSpec, Finding, Frame


def detect(frame: Frame) -> list[Finding]:
    df = frame.df
    if df.empty:
        return []
    exact = df.duplicated(keep="first")
    normalized = df.apply(lambda s: s.astype("string").str.strip().str.casefold())
    near = normalized.duplicated(keep="first") & ~exact
    findings = []
    if exact.any():
        findings.append(Finding(
            "duplicates", None, int(exact.sum()),
            "Quarantine the repeated rows, keeping the first of each.",
            [int(i) for i in df.index[exact][:5]], {"kind": "exact"},
        ))
    if near.any():
        findings.append(Finding(
            "duplicates", None, int(near.sum()),
            "Review rows that match another row apart from spacing or case; quarantine confirmed repeats.",
            [int(i) for i in df.index[near][:5]], {"kind": "near"},
        ))
    return findings


SPEC = DetectorSpec(
    "duplicates", "duplicate rows", "Rows that repeat another row exactly, or apart from spacing or case.",
    group="records", weight=0.8, default_level="skews", scope="rows", detect=detect,
)
