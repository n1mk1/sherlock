"""Exact and near duplicate rows (near: equal after trimming and case-folding every value).
Examples are `_row_id`s."""

from sherlock.cleaning.detectors.base import DetectorSpec, Finding, Frame, Injector
from sherlock.cleaning.detectors.fixtures import clean_frame


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


def damage(df, column: str, rows: list[int], rng) -> dict:
    """Each chosen row made a copy, in every column, of a row that isn't chosen."""
    chosen = set(rows)
    others = [i for i in range(len(df)) if i not in chosen]
    out = {}
    for i in rows:
        source = rng.choice(others)
        for c in df.columns:
            if df.at[i, c] != df.at[source, c]:
                out[(i, c)] = df.at[source, c]
    return out


SPEC = DetectorSpec(
    "duplicates", "duplicate rows", "Rows that repeat another row exactly, or apart from spacing or case.",
    group="records", weight=0.8, default_level="skews", scope="rows", detect=detect,
    injectors={"repeat": Injector(damage)}, clean_fixture=lambda: (clean_frame(), "record_id"),
)
